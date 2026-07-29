import os
import sqlite3
import json
import pandas as pd
import gradio as gr

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "leads.db")

def get_leads_df(canton_filter="All", niche_filter="All", search_query=""):
    if not os.path.exists(DB_PATH):
        return pd.DataFrame(columns=["Company Name", "Phone", "Decision Maker", "Title", "Canton", "Niche", "Fit Score", "Size Band", "Website"])
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    query = "SELECT company_name, phone, decision_maker, decision_title, canton, niche, fit_score, size_band, website FROM leads WHERE status != 'rejected'"
    params = []
    
    if canton_filter != "All":
        query += " AND canton = ?"
        params.append(canton_filter)
        
    if niche_filter != "All":
        query += " AND niche = ?"
        params.append(niche_filter)
        
    if search_query:
        query += " AND (company_name LIKE ? OR decision_maker LIKE ? OR phone LIKE ?)"
        term = f"%{search_query}%"
        params.extend([term, term, term])
        
    query += " ORDER BY fit_score DESC"
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    data = []
    for r in rows:
        data.append({
            "Company Name": r["company_name"],
            "Phone": r["phone"],
            "Decision Maker": r["decision_maker"] or "N/A",
            "Title": r["decision_title"] or "Owner",
            "Canton": r["canton"],
            "Niche": r["niche"],
            "Fit Score": r["fit_score"] or 0,
            "Size Band": r["size_band"] or "small",
            "Website": r["website"] or ""
        })
        
    return pd.DataFrame(data)

def export_csv_file():
    df = get_leads_df()
    export_path = os.path.join(os.path.dirname(__file__), "exports", "astraquote_leads.csv")
    os.makedirs(os.path.dirname(export_path), exist_ok=True)
    df.to_csv(export_path, index=False)
    return export_path

def export_excel_file():
    df = get_leads_df()
    export_path = os.path.join(os.path.dirname(__file__), "exports", "astraquote_leads.xlsx")
    os.makedirs(os.path.dirname(export_path), exist_ok=True)
    with pd.ExcelWriter(export_path, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Leads', index=False)
    return export_path

def get_stats():
    if not os.path.exists(DB_PATH):
        return "0 Leads Discovered", "0 Qualified ICP", "0 Cantons"
    
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    qualified = conn.execute("SELECT COUNT(*) FROM leads WHERE status != 'rejected'").fetchone()[0]
    cantons = conn.execute("SELECT COUNT(DISTINCT canton) FROM leads WHERE status != 'rejected'").fetchone()[0]
    conn.close()
    
    return f"{total} Leads Scanned", f"{qualified} ICP Qualified", f"{cantons} Swiss Cantons"

with gr.Blocks(title="AstraQuote B2B Swiss Trade Lead Engine", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🚰 AstraQuote Swiss Trade Lead Engine")
    gr.Markdown("### Real-Time Qualified B2B Leads for Swiss Plumbing, HVAC, & Sanitaire Companies")
    
    with gr.Row():
        stat1 = gr.Textbox(label="Total Processed", value=get_stats()[0], interactive=False)
        stat2 = gr.Textbox(label="Delivered Qualified Leads", value=get_stats()[1], interactive=False)
        stat3 = gr.Textbox(label="Cantons Covered", value=get_stats()[2], interactive=False)
        
    with gr.Row():
        canton_dropdown = gr.Dropdown(choices=["All", "Genève", "Vaud", "Valais", "Neuchâtel", "Jura"], value="All", label="Filter by Canton")
        niche_dropdown = gr.Dropdown(choices=["All", "plomberie", "chauffage", "sanitaire", "climatisation"], value="All", label="Filter by Niche")
        search_box = gr.Textbox(placeholder="Search company, contact, or phone...", label="Search Leads")
        
    leads_table = gr.Dataframe(value=get_leads_df(), label="Qualified Swiss B2B Leads", interactive=False)
    
    canton_dropdown.change(fn=get_leads_df, inputs=[canton_dropdown, niche_dropdown, search_box], outputs=leads_table)
    niche_dropdown.change(fn=get_leads_df, inputs=[canton_dropdown, niche_dropdown, search_box], outputs=leads_table)
    search_box.change(fn=get_leads_df, inputs=[canton_dropdown, niche_dropdown, search_box], outputs=leads_table)
    
    gr.Markdown("### 📥 Download Lead Exports")
    with gr.Row():
        btn_csv = gr.Button("📄 Download CSV Export", variant="primary")
        btn_excel = gr.Button("📊 Download Excel Export", variant="primary")
        file_output = gr.File(label="Download File Output")
        
    btn_csv.click(fn=export_csv_file, outputs=file_output)
    btn_excel.click(fn=export_excel_file, outputs=file_output)

if __name__ == "__main__":
    demo.launch()
