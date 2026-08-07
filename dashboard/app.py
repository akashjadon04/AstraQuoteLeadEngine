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
    if get_engine_mode() == "global":
        db_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'global_leads.db')
    else:
        db_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'leads.db')
    init_db(db_file)
    conn = sqlite3.connect(db_file)
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
    # Map NOGA label
    noga = d.get('noga_code')
    if noga in ('43.22A', '432201'):
        d['noga_label'] = 'NOGA 43.22A — Installation sanitaire & Plomberie'
        d['noga_code_display'] = 'NOGA 43.22A'
    elif noga in ('43.22B', '432202'):
        d['noga_label'] = 'NOGA 43.22B — Installation de chauffage & Climatisation'
        d['noga_code_display'] = 'NOGA 43.22B'
    else:
        d['noga_label'] = 'NOGA 43.22 — Installation sanitaire & Chauffage'
        d['noga_code_display'] = 'NOGA 43.22'
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

from utils.niche_profiles import get_active_profile, set_active_profile_id, list_profiles
from utils.country_profiles import get_active_country, set_active_country_code, list_countries

# APIs
@app.route('/api/profiles')
def api_profiles():
    return jsonify(list_profiles())

@app.route('/api/profile', methods=['GET', 'POST'])
def api_profile():
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        pid = data.get('profile_id')
        if pid and set_active_profile_id(pid):
            return jsonify({"status": "success", "active_profile": get_active_profile().to_dict()})
        return jsonify({"status": "error", "message": "Invalid profile_id"}), 400
    return jsonify(get_active_profile().to_dict())

@app.route('/api/countries')
def api_countries():
    return jsonify(list_countries())

@app.route('/api/country', methods=['GET', 'POST'])
def api_country():
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        code = data.get('country_code')
        if code and set_active_country_code(code):
            set_engine_mode('global')
            import subprocess, sys
            cmd = [sys.executable, "global_main.py"]
            subprocess.Popen(cmd, cwd=os.path.dirname(os.path.dirname(__file__)))
            return jsonify({"status": "success", "active_country": get_active_country().to_dict(), "message": f"Global Lead Engine launched for {code}."})
        return jsonify({"status": "error", "message": "Invalid country_code"}), 400
    return jsonify(get_active_country().to_dict())


ENGINE_MODE_FILE = "data/engine_mode.json"

def get_engine_mode() -> str:
    if os.path.exists(ENGINE_MODE_FILE):
        try:
            with open(ENGINE_MODE_FILE, "r") as f:
                return json.load(f).get("mode", "swiss")
        except Exception:
            pass
    return "swiss"

def set_engine_mode(mode: str) -> str:
    m = "global" if mode == "global" else "swiss"
    os.makedirs("data", exist_ok=True)
    with open(ENGINE_MODE_FILE, "w") as f:
        json.dump({"mode": m}, f)
    return m

@app.route('/api/engine/mode', methods=['GET', 'POST'])
def api_engine_mode():
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        m = data.get('mode')
        new_mode = set_engine_mode(m)
        return jsonify({"status": "success", "mode": new_mode})
    return jsonify({"mode": get_engine_mode()})


@app.route('/api/global/pipeline/start', methods=['POST'])
def api_global_pipeline_start():
    import subprocess
    cmd = [sys.executable, "global_main.py"]
    subprocess.Popen(cmd, cwd=os.path.dirname(os.path.dirname(__file__)))
    return jsonify({"status": "success", "message": "Global Lead Engine pipeline started in background."})




@app.route('/api/leads')
def api_leads():
    if request.args.get('source') == 'master':
        master_path = "data/qualified_master.db"
        if not os.path.exists(master_path):
            return jsonify([])
        conn = sqlite3.connect(master_path)
        conn.row_factory = sqlite3.Row
    else:
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

    if request.args.get('qualified_only') == '1':
        conditions.append("decision_maker IS NOT NULL AND decision_maker != '' AND phone IS NOT NULL AND phone != ''")


    niche = request.args.get('niche')
    if niche:
        conditions.append('niche = ?')
        params.append(niche)

    noga = request.args.get('noga')
    if noga:
        conditions.append('noga_code = ?')
        params.append(noga)

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

@app.route('/api/master_qualified')
def api_master_qualified():
    master_path = "data/qualified_master.db"
    if not os.path.exists(master_path):
        return jsonify([])
    conn = sqlite3.connect(master_path)
    conn.row_factory = sqlite3.Row
    leads = conn.execute("SELECT * FROM leads WHERE status = 'enriched' ORDER BY fit_score DESC").fetchall()
    conn.close()
    return jsonify([dict_from_row(row) for row in leads])

@app.route('/api/stats')
def api_stats():
    conn = get_db_connection()
    total_leads = conn.execute('SELECT COUNT(*) FROM leads').fetchone()[0]
    qualified_leads = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE decision_maker IS NOT NULL AND decision_maker != '' "
        "AND phone IS NOT NULL AND phone != ''"
    ).fetchone()[0]
    no_contact = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE decision_maker IS NULL OR decision_maker = ''"
    ).fetchone()[0]

    avg_urgency = conn.execute('SELECT AVG(urgency_score) FROM leads').fetchone()[0] or 0
    avg_digital = conn.execute('SELECT AVG(digital_maturity) FROM leads').fetchone()[0] or 0
    avg_fit = conn.execute('SELECT AVG(fit_score) FROM leads').fetchone()[0] or 0

    # Canton distribution
    canton_rows = conn.execute('SELECT canton, COUNT(*) as count FROM leads GROUP BY canton').fetchall()
    canton_dist = {row['canton']: row['count'] for row in canton_rows if row['canton']}

    # Niche distribution
    niche_rows = conn.execute('SELECT niche, COUNT(*) as count FROM leads GROUP BY niche').fetchall()
    niche_dist = {row['niche']: row['count'] for row in niche_rows if row['niche']}

    # NOGA distribution
    noga_rows = conn.execute('SELECT noga_code, COUNT(*) as count FROM leads GROUP BY noga_code').fetchall()
    noga_dist = {row['noga_code'] or '432201': row['count'] for row in noga_rows}

    # Urgency distribution
    urgency_dist = {'High (8-10)': 0, 'Medium (5-7)': 0, 'Low (1-4)': 0}
    urgency_rows = conn.execute('SELECT urgency_score FROM leads WHERE urgency_score IS NOT NULL').fetchall()
    for row in urgency_rows:
        score = row['urgency_score']
        if score >= 8: urgency_dist['High (8-10)'] += 1
        elif score >= 5: urgency_dist['Medium (5-7)'] += 1
        else: urgency_dist['Low (1-4)'] += 1

    # Fit score distribution
    fit_dist = {'Qualified (75+)': 0, 'Good (50-74)': 0, 'Fair (25-49)': 0, 'Poor (<25)': 0}
    fit_rows = conn.execute('SELECT fit_score FROM leads WHERE fit_score IS NOT NULL').fetchall()
    for row in fit_rows:
        score = row['fit_score'] or 0
        if score >= 75: fit_dist['Qualified (75+)'] += 1
        elif score >= 50: fit_dist['Good (50-74)'] += 1
        elif score >= 25: fit_dist['Fair (25-49)'] += 1
        else: fit_dist['Poor (<25)'] += 1

    # Strict ICP-qualified count: good fit score AND a named contact.
    icp_qualified = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE fit_score >= 75 "
        "AND decision_maker IS NOT NULL AND decision_maker != ''"
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

def _get_export_connection():
    target_engine = request.args.get('engine')
    if not target_engine:
        target_engine = get_engine_mode()
    
    if target_engine == 'global':
        db_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'global_leads.db')
    else:
        db_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'leads.db')
        if not os.path.exists(db_file) or os.path.getsize(db_file) == 0:
            db_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'qualified_master.db')
            
    init_db(db_file)
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn

def _export_rows(conn):
    """Rows for an export. Returns all qualified leads sorted by fit score."""
    if request.args.get('all') == '1':
        return conn.execute('SELECT * FROM leads ORDER BY fit_score DESC').fetchall()
    return conn.execute("SELECT * FROM leads WHERE status != 'rejected' ORDER BY fit_score DESC").fetchall()


@app.route('/api/export/csv')
def export_csv():
    conn = _get_export_connection()
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
    conn = _get_export_connection()
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
    conn = _get_export_connection()
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
        
@app.route('/api/export/json')
def export_json():
    conn = get_db_connection()
    leads_rows = _export_rows(conn)
    conn.close()
    data = [dict_from_row(row) for row in leads_rows]
    return Response(
        json.dumps(data, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-disposition": "attachment; filename=astraquote_leads.json"}
    )


import threading
import asyncio
from utils.state_manager import update_state, get_state

# Detect cloud/Render mode — pipeline disabled to stay in 512MB RAM.
# Render platform auto-injects RENDER=true; our render.yaml also sets RENDER=1.
# Check for any truthy value so both are caught.
_RENDER_ENV = os.environ.get("RENDER", "").lower()
_RENDER_MODE = _RENDER_ENV in ("1", "true", "yes")

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
    tmp_path = DB_PATH + '.tmp'
    db_file.save(tmp_path)
    # Validate it's actually a SQLite file
    with open(tmp_path, 'rb') as f:
        header = f.read(16)
    if not header.startswith(b'SQLite format 3'):
        os.remove(tmp_path)
        return jsonify({"error": "Invalid SQLite file"}), 400
    shutil.move(tmp_path, DB_PATH)
    # Count what we just received
    conn = get_db_connection()
    total = conn.execute('SELECT COUNT(*) FROM leads').fetchone()[0]
    qualified = conn.execute("SELECT COUNT(*) FROM leads WHERE status='enriched'").fetchone()[0]
    conn.close()
    print(f"[SYNC] DB uploaded: {total} leads, {qualified} qualified")
    return jsonify({"status": "ok", "total": total, "qualified": qualified})

@app.route('/api/blacklist/import', methods=['POST'])
def import_blacklist():
    """Import a list of previously called leads (phones or company names)
    into the permanent blacklist table so they are NEVER re-contacted or delivered."""
    from utils.database import add_to_blacklist
    from layers.layer1_discovery import normalize_name

    entries = []
    if request.is_json:
        data = request.get_json() or {}
        entries = data.get('entries', [])

    if 'file' in request.files:
        file = request.files['file']
        content = file.read().decode('utf-8', errors='ignore')
        lines = content.splitlines()
        reader = csv.reader(lines)
        for row in reader:
            for item in row:
                if item.strip():
                    entries.append(item.strip())

    added = 0
    for entry in entries:
        entry_str = str(entry).strip()
        if not entry_str:
            continue
        phone = _validate_swiss_phone(entry_str) or entry_str
        name_key = normalize_name(entry_str)
        add_to_blacklist(phone, entry_str, name_key)
        added += 1

    return jsonify({"status": "ok", "added": added, "message": f"Successfully blacklisted {added} previously called leads."})

@app.route('/api/pipeline/start', methods=['POST'])
def start_pipeline_route():
    global pipeline_thread
    if pipeline_thread and pipeline_thread.is_alive():
        return jsonify({"status": "error", "message": "Pipeline is already running"}), 400

    # Try triggering GitHub Actions dispatch if token is available
    gh_token = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
    if gh_token:
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://api.github.com/repos/akashjadon04/AstraQuoteLeadEngine/actions/workflows/pipeline.yml/dispatches",
                data=json.dumps({"ref": "main"}).encode('utf-8'),
                headers={
                    "Authorization": f"Bearer {gh_token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "AstraQuoteDashboard"
                },
                method="POST"
            )
            with urllib.request.urlopen(req) as resp:
                if resp.status in (200, 204):
                    update_state({
                        "status": "running",
                        "current_layer": 1,
                        "current_layer_name": "Discovery",
                        "stop_requested": False,
                        "last_log": "Pipeline dispatched on GitHub Cloud runner (7GB RAM)..."
                    })
                    return jsonify({"status": "success", "message": "Pipeline triggered on GitHub Actions cloud runner"})
        except Exception as e:
            print("GitHub dispatch fallback to local worker:", e)

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
