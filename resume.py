import asyncio
from rich.console import Console
from rich.panel import Panel

import config
from utils.database import init_db, get_leads
from utils.state_manager import update_state
from layers.layer5_research import batch_research
from layers.layer6_enrich import batch_enrich
from layers.layer7_dashboard import refresh_dashboard_data

console = Console()

async def resume_pipeline():
    init_db(config.DB_PATH)
    
    # Get all leads that made it past the quota gate (layer 4)
    all_top = get_leads(layer=4)
    
    if not all_top:
        console.print("[red]No leads found at layer 4+![/red]")
        return
        
    console.print(f"[bold yellow]Found {len(all_top)} leads at layer 4+ to resume processing...[/bold yellow]")
    
    # ── LAYER 5: Deep Research
    needs_research = [l for l in all_top if l.get("layer_reached", 0) < 5]
    if needs_research:
        update_state({
            "current_layer": 5,
            "current_layer_name": "Deep Research",
            "last_log": f"Performing deep public-info research on {len(needs_research)} remaining leads..."
        })
        console.print(f"[bold cyan] LAYER 5: RESEARCHING {len(needs_research)} LEADS [/bold cyan]")
        await batch_research(needs_research)
    
    # Refresh all_top to get newly researched data
    all_top = get_leads(layer=4)
    
    # ── LAYER 6: Enrichment
    needs_enrich = [l for l in all_top if l.get("layer_reached", 0) < 6]
    if needs_enrich:
        update_state({
            "current_layer": 6,
            "current_layer_name": "Contact Enrichment",
            "last_log": f"Enriching {len(needs_enrich)} remaining leads..."
        })
        console.print(f"[bold cyan] LAYER 6: ENRICHING {len(needs_enrich)} LEADS [/bold cyan]")
        await batch_enrich(needs_enrich)
        
    all_top = get_leads(layer=4)
    console.print(f"[green]✓ Layer 6 complete:[/green] All leads fully enriched")

    # Blacklist update — by phone AND normalized name, so a future run
    # recognizes this company again even under a different phone number.
    from utils.database import add_to_blacklist
    from layers.layer1_discovery import normalize_name
    for lead in all_top:
        if lead.get("phone"):
            add_to_blacklist(lead["phone"], lead.get("company_name", ""),
                              normalize_name(lead.get("company_name", "")))

    # ── LAYER 7: Dashboard
    update_state({
        "current_layer": 7,
        "current_layer_name": "Dashboard",
        "last_log": "Refreshing dashboard data..."
    })
    console.print("[bold cyan] LAYER 7: DASHBOARD GENERATION [/bold cyan]")
    refresh_dashboard_data()
    
    update_state({
        "status": "completed",
        "last_log": "Pipeline execution completed successfully."
    })
    console.print(f"[green]✓ Dashboard ready at {config.DASHBOARD_URL}[/green]")

if __name__ == "__main__":
    asyncio.run(resume_pipeline())
