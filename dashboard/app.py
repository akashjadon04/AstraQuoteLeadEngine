import os
import sqlite3
import json
import csv
from io import StringIO, BytesIO
from flask import Flask, render_template, request, jsonify, send_file, Response, abort
from dashboard.pdf_generator import generate_full_report, generate_lead_card, WEASYPRINT_AVAILABLE
import pandas as pd

from utils.database import init_db, get_current_run_info
from utils.scoring import classify_contact_tier

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# Make sure this matches your project config path
try:
    import config as _cfg
    DB_PATH = _cfg.DB_PATH
except ImportError:
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'leads.db')

# Always initialize through the single source of truth for the schema (utils.database).
# The dashboard used to create its own ad-hoc table here, which had a different set of
# columns from the real pipeline schema — if the dashboard was ever launched standalone
# before a pipeline run, every later insert/update from the layers would fail with
# "no such column" errors. init_db() is idempotent (CREATE TABLE IF NOT EXISTS + guarded
# migrations), so calling it here is safe.
init_db(DB_PATH)


def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def dict_from_row(row):
    if not row:
        return {}
    d = dict(row)
    # Map database column names to template keys
    d['decision_maker_name'] = d.get('decision_maker')
    d['decision_maker_title'] = d.get('decision_title')
    d['decision_maker_linkedin'] = d.get('decision_maker_linkedin')
    d['digital_score'] = d.get('digital_maturity')
    d['pitch_strategy'] = d.get('pitch_angle')
    d['custom_opening_line'] = d.get('custom_opening')
    d['contact_tier'] = classify_contact_tier(d)
    # Generate Google review summary if not stored
    rating = d.get('google_rating')
    reviews = d.get('google_reviews')
    if rating is not None:
        d['google_review_summary'] = f"Note moyenne de {rating}/5 basée sur {reviews or 0} avis Google."
    else:
        d['google_review_summary'] = "Aucun avis client Google disponible pour le moment."
    return d

@app.route('/')
def index():
    return render_template('overview.html')

@app.route('/leads')
def leads():
    return render_template('leads.html')

@app.route('/leads/<int:lead_id>')
def lead_detail(lead_id):
    conn = get_db_connection()
    lead = conn.execute('SELECT * FROM leads WHERE id = ?', (lead_id,)).fetchone()
    conn.close()
    if lead is None:
        abort(404)
    lead_dict = dict_from_row(lead)

    # Parse JSON fields if necessary
    for field in ['pain_points', 'social_links', 'fit_score_breakdown', 'size_signals']:
        if lead_dict.get(field):
            try:
                lead_dict[field] = json.loads(lead_dict[field])
            except:
                pass

    return render_template('lead_detail.html', lead=lead_dict)

@app.route('/export')
def export_panel():
    return render_template('export.html')

# APIs
@app.route('/api/leads')
def api_leads():
    conn = get_db_connection()
    query = 'SELECT * FROM leads'
    
    # Simple filtering
    conditions = []
    params = []
    
    canton = request.args.get('canton')
    if canton:
        conditions.append('canton = ?')
        params.append(canton)

    status = request.args.get('status')
    if status:
        conditions.append('status = ?')
        params.append(status)
    else:
        # Default view = the delivered set. 'rejected' leads (processed but
        # excluded from the final TARGET_LEAD_COUNT — no contact found,
        # research incomplete, or just ranked lower) stay in the DB for
        # transparency but shouldn't clutter the main list unless asked for.
        conditions.append("status != 'rejected'")

    niche = request.args.get('niche')
    if niche:
        conditions.append('niche = ?')
        params.append(niche)

    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)

    # Default sort is fit score — how well the business matches who actually
    # buys AstraQuote — not urgency/digital maturity, which are about the
    # pitch angle, not whether this is a good lead in the first place.
    sort_columns = {
        'fit': 'fit_score DESC, urgency_score DESC',
        'size': ("CASE size_band WHEN 'established' THEN 4 WHEN 'small' THEN 3 "
                 "WHEN 'unknown' THEN 2 WHEN 'micro' THEN 1 ELSE 0 END DESC, fit_score DESC"),
        'urgency': 'urgency_score DESC, fit_score DESC',
        'digital': 'digital_maturity DESC, fit_score DESC',
        'recent': 'discovered_at DESC',
    }
    sort = request.args.get('sort', 'fit')
    query += ' ORDER BY ' + sort_columns.get(sort, sort_columns['fit'])

    leads_rows = conn.execute(query, params).fetchall()
    conn.close()

    return jsonify([dict_from_row(row) for row in leads_rows])

@app.route('/api/stats')
def api_stats():
    conn = get_db_connection()
    total_leads = conn.execute('SELECT COUNT(*) FROM leads').fetchone()[0]
    qualified_leads = conn.execute("SELECT COUNT(*) FROM leads WHERE status IN ('qualified', 'researched', 'enriched')").fetchone()[0]
    avg_urgency = conn.execute('SELECT AVG(urgency_score) FROM leads').fetchone()[0] or 0
    avg_digital = conn.execute('SELECT AVG(digital_maturity) FROM leads').fetchone()[0] or 0
    avg_fit = conn.execute('SELECT AVG(fit_score) FROM leads').fetchone()[0] or 0

    # Canton distribution
    canton_rows = conn.execute('SELECT canton, COUNT(*) as count FROM leads GROUP BY canton').fetchall()
    canton_dist = {row['canton']: row['count'] for row in canton_rows if row['canton']}

    # Niche distribution
    niche_rows = conn.execute('SELECT niche, COUNT(*) as count FROM leads GROUP BY niche').fetchall()
    niche_dist = {row['niche']: row['count'] for row in niche_rows if row['niche']}

    # Urgency distribution
    urgency_dist = {'High (8-10)': 0, 'Medium (5-7)': 0, 'Low (1-4)': 0}
    urgency_rows = conn.execute('SELECT urgency_score FROM leads WHERE urgency_score IS NOT NULL').fetchall()
    for row in urgency_rows:
        score = row['urgency_score']
        if score >= 8: urgency_dist['High (8-10)'] += 1
        elif score >= 5: urgency_dist['Medium (5-7)'] += 1
        else: urgency_dist['Low (1-4)'] += 1

    # Fit score distribution — the "potential" axis, kept separate from urgency/
    # digital maturity above, which are about pitch angle, not lead quality.
    fit_dist = {'Qualified (75+)': 0, 'Good (50-74)': 0, 'Fair (25-49)': 0, 'Poor (<25)': 0}
    fit_rows = conn.execute('SELECT fit_score FROM leads WHERE fit_score IS NOT NULL').fetchall()
    for row in fit_rows:
        score = row['fit_score'] or 0
        if score >= 75: fit_dist['Qualified (75+)'] += 1
        elif score >= 50: fit_dist['Good (50-74)'] += 1
        elif score >= 25: fit_dist['Fair (25-49)'] += 1
        else: fit_dist['Poor (<25)'] += 1

    # Strict ICP-qualified count: good fit score AND a named contact. A lead
    # can't be outreach-ready without both — see utils.scoring.compute_fit_score.
    icp_qualified = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE fit_score >= 75 "
        "AND decision_maker IS NOT NULL AND decision_maker != ''"
    ).fetchone()[0]
    no_contact = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE (decision_maker IS NULL OR decision_maker = '') "
        "AND status IN ('qualified', 'researched', 'enriched')"
    ).fetchone()[0]

    # Company-size estimate distribution (the "is it big enough" axis) and how
    # many otherwise-complete leads were set aside purely for being too small.
    _band_labels = {"established": "Established (~10+)", "small": "Small team (~4-9)",
                    "micro": "Micro (~2-3)", "sole_trader": "Sole trader (~1)", "unknown": "Unknown"}
    size_dist = {label: 0 for label in _band_labels.values()}
    for row in conn.execute("SELECT size_band, COUNT(*) as c FROM leads WHERE size_band IS NOT NULL GROUP BY size_band").fetchall():
        size_dist[_band_labels.get(row['size_band'], 'Unknown')] += row['c']
    too_small = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE status='rejected' AND elimination_reasons LIKE '%too small%'"
    ).fetchone()[0]

    conn.close()

    # Every lead in the table belongs to whichever run last wiped and
    # regenerated it (see utils.database.start_new_run) — surfaced so it's
    # never ambiguous whether what you're looking at is the current batch.
    run_info = get_current_run_info()

    return jsonify({
        'total_leads': total_leads,
        'qualified_leads': qualified_leads,
        'avg_urgency': round(avg_urgency, 1),
        'avg_digital_maturity': round(avg_digital, 1),
        'avg_fit_score': round(avg_fit, 1),
        'canton_distribution': canton_dist,
        'niche_distribution': niche_dist,
        'urgency_distribution': urgency_dist,
        'fit_distribution': fit_dist,
        'size_distribution': size_dist,
        'icp_qualified_leads': icp_qualified,
        'no_contact_count': no_contact,
        'too_small_count': too_small,
        'current_run_id': run_info['run_id'],
        'current_run_count': run_info['count'],
        'current_run_last_updated': run_info['last_updated'],
    })

@app.route('/api/pipeline-status')
def api_pipeline_status():
    from utils.state_manager import get_state
    return jsonify(get_state())

def _export_rows(conn):
    """Rows for an export. Defaults to the CURRENT delivered batch only
    (status='enriched') — the same 50 the dashboard shows by default — not
    every candidate this run tried (status='rejected': too small, no contact,
    duplicate, etc.) and never a past run's leftovers, since those no longer
    exist in the table at all once a new run has wiped and replaced them (see
    utils.database.start_new_run). Pass ?all=1 to export literally everything
    still in the table, rejected rows included, for debugging/audit."""
    if request.args.get('all') == '1':
        return conn.execute('SELECT * FROM leads').fetchall()
    return conn.execute("SELECT * FROM leads WHERE status = 'enriched'").fetchall()


@app.route('/api/export/csv')
def export_csv():
    conn = get_db_connection()
    leads_rows = _export_rows(conn)
    conn.close()

    data = [dict_from_row(row) for row in leads_rows]
    df = pd.DataFrame(data)

    output = StringIO()
    df.to_csv(output, index=False)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=astraquote_leads.csv"}
    )

@app.route('/api/export/excel')
def export_excel():
    conn = get_db_connection()
    leads_rows = _export_rows(conn)
    conn.close()

    data = [dict_from_row(row) for row in leads_rows]
    df = pd.DataFrame(data)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Leads', index=False)

    output.seek(0)

    return send_file(
        output,
        download_name="astraquote_leads.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route('/api/export/pdf')
def export_pdf():
    conn = get_db_connection()
    leads_rows = _export_rows(conn)
    conn.close()

    leads = [dict_from_row(row) for row in leads_rows]
    
    # Need a temporary file
    temp_pdf = os.path.join(os.path.dirname(__file__), 'temp_report.pdf')
    generate_full_report(leads, temp_pdf)
    
    if not WEASYPRINT_AVAILABLE:
        return send_file(
            temp_pdf,
            download_name="astraquote_full_report.html",
            as_attachment=True,
            mimetype="text/html"
        )
        
    return send_file(
        temp_pdf,
        download_name="astraquote_full_report.pdf",
        as_attachment=True,
        mimetype="application/pdf"
    )

@app.route('/api/export/pdf/<int:lead_id>')
def export_pdf_single(lead_id):
    conn = get_db_connection()
    lead = conn.execute('SELECT * FROM leads WHERE id = ?', (lead_id,)).fetchone()
    conn.close()
    
    if not lead:
        abort(404)
        
    lead_dict = dict_from_row(lead)
    
    temp_pdf = os.path.join(os.path.dirname(__file__), f'temp_lead_{lead_id}.pdf')
    generate_lead_card(lead_dict, temp_pdf)
    
    if not WEASYPRINT_AVAILABLE:
        return send_file(
            temp_pdf,
            download_name=f"astraquote_lead_{lead_id}.html",
            as_attachment=True,
            mimetype="text/html"
        )
        
    return send_file(
        temp_pdf,
        download_name=f"astraquote_lead_{lead_id}.pdf",
        as_attachment=True,
        mimetype="application/pdf"
    )

import threading
import asyncio
from utils.state_manager import update_state, get_state

# Detect cloud/Render mode — pipeline disabled to stay in 512MB RAM
_RENDER_MODE = os.environ.get("RENDER", "") == "1"

pipeline_thread = None
update_state({"status": "idle", "stop_requested": False, "last_log": "System initialized and ready."})

def run_background_pipeline():
    """Heavy imports done INSIDE the function so they only load on local PC,
    not on Render where they would blow the 512MB RAM limit on startup."""
    import gc
    from main import run_pipeline, reconcile_and_finalize_run
    from utils.database import get_current_run_info
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        gc.collect()  # clean slate before starting
        loop.run_until_complete(run_pipeline())
        gc.collect()  # free memory after completion
    except MemoryError:
        msg = "Out of memory — pipeline stopped. Use your local PC to run the pipeline, then sync."
        print(f"[OOM] {msg}")
        update_state({"status": "error", "last_log": msg})
        try:
            run_info = get_current_run_info()
            if run_info.get("run_id"):
                reconcile_and_finalize_run(run_info["run_id"])
        except Exception:
            pass
    except Exception as e:
        import traceback
        print("Error running background pipeline:", traceback.format_exc())
        try:
            from utils.database import get_current_run_info
            from main import reconcile_and_finalize_run
            run_info = get_current_run_info()
            if run_info.get("run_id"):
                reconcile_and_finalize_run(run_info["run_id"])
        except Exception as reconcile_error:
            print("Error reconciling interrupted run:", reconcile_error)
        update_state({"status": "error", "last_log": f"Pipeline error: {str(e)}"})
    finally:
        gc.collect()
        loop.close()

@app.route('/api/mode')
def api_mode():
    """Tells the frontend whether this is Render cloud mode or local PC mode."""
    return jsonify({
        "mode": "cloud" if _RENDER_MODE else "local",
        "pipeline_enabled": not _RENDER_MODE,
        "message": "Cloud viewer mode — run pipeline on your local PC and sync results here." if _RENDER_MODE else "Local mode — full pipeline available."
    })

@app.route('/api/upload-db', methods=['POST'])
def upload_db():
    """Accepts a SQLite DB file upload from the local sync script.
    Replaces the cloud DB with the freshly-run local results.
    Secured by a token check."""
    import shutil, hashlib
    token = request.headers.get('X-Sync-Token', '')
    expected = os.environ.get('SYNC_TOKEN', 'astraquote-sync-2024')
    if not token or token != expected:
        return jsonify({"error": "Unauthorized"}), 401
    if 'db' not in request.files:
        return jsonify({"error": "No db file in request"}), 400
    db_file = request.files['db']
    tmp_path = config.DB_PATH + '.tmp'
    db_file.save(tmp_path)
    # Validate it's actually a SQLite file
    with open(tmp_path, 'rb') as f:
        header = f.read(16)
    if not header.startswith(b'SQLite format 3'):
        os.remove(tmp_path)
        return jsonify({"error": "Invalid SQLite file"}), 400
    shutil.move(tmp_path, config.DB_PATH)
    # Count what we just received
    conn = get_db_connection()
    total = conn.execute('SELECT COUNT(*) FROM leads').fetchone()[0]
    qualified = conn.execute("SELECT COUNT(*) FROM leads WHERE status='enriched'").fetchone()[0]
    conn.close()
    print(f"[SYNC] DB uploaded: {total} leads, {qualified} qualified")
    return jsonify({"status": "ok", "total": total, "qualified": qualified})

@app.route('/api/pipeline/start', methods=['POST'])
def start_pipeline_route():
    global pipeline_thread
    if _RENDER_MODE:
        return jsonify({
            "status": "cloud_mode",
            "message": "Pipeline disabled on Render (512MB RAM limit). Run on your local PC and sync results here using: python sync_to_render.py"
        }), 200
    if pipeline_thread and pipeline_thread.is_alive():
        return jsonify({"status": "error", "message": "Pipeline is already running"}), 400
    update_state({
        "status": "running",
        "current_layer": 1,
        "current_layer_name": "Discovery",
        "stop_requested": False,
        "last_log": "Starting pipeline from dashboard control center..."
    })
    pipeline_thread = threading.Thread(target=run_background_pipeline, daemon=True)
    pipeline_thread.start()
    return jsonify({"status": "success", "message": "Pipeline started"})


@app.route('/api/pipeline/stop', methods=['POST'])
def stop_pipeline_route():
    update_state({
        "stop_requested": True,
        "last_log": "Stop command sent. Waiting for pipeline to cancel..."
    })
    return jsonify({"status": "success", "message": "Stop request sent"})

@app.route('/api/pipeline/continue', methods=['POST'])
def continue_pipeline_route():
    return start_pipeline_route()

@app.route('/api/pipeline/logs')
def api_pipeline_logs():
    log_file = "data/engine.log"
    if not os.path.exists(log_file):
        return jsonify([])
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        import re
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        cleaned_lines = []
        for line in lines[-40:]:
            cleaned_lines.append(ansi_escape.sub('', line).strip())
        return jsonify(cleaned_lines)
    except Exception:
        return jsonify([])

@app.route('/api/pipeline/reset', methods=['POST'])
def reset_pipeline_route():
    from utils.database import clear_db
    clear_db()
    
    # Clear engine log file
    log_file = "data/engine.log"
    if os.path.exists(log_file):
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                f.truncate(0)
        except Exception as e:
            print("Error clearing log file:", e)
            
    update_state({
        "status": "idle",
        "current_layer": 1,
        "current_layer_name": "Discovery",
        "stop_requested": False,
        "leads_discovered": 0,
        "leads_filtered": 0,
        "leads_qualified": 0,
        "leads_researched": 0,
        "leads_enriched": 0,
        "last_log": "System reset. Database cleared. Ready to start from scratch."
    })
    return jsonify({"status": "success", "message": "Database and progress cleared."})

if __name__ == '__main__':
    try:
        import config as _cfg
        app.run(debug=True, host=_cfg.DASHBOARD_HOST, port=_cfg.DASHBOARD_PORT)
    except ImportError:
        app.run(debug=True, port=8800)
