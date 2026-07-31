# ============================================================
# main.py — AstraQuote Lead Engine — 7-Layer Pipeline Runner
# ============================================================
# Enterprise-grade B2B lead generation for Swiss trade businesses.
# Discovers, filters, researches, and presents 100 qualified leads
# with rule-based pain-point analysis and pitch strategies — no
# external AI/LLM, purely logic over publicly available data.
#
# Built by Evolnex.digital
# ============================================================

import asyncio
import argparse
import json
import sys
import os
import time
from datetime import datetime

# Force UTF-8 output for Windows console
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich import print as rprint

import config
from utils.database import init_db, get_lead_count, get_stats, get_leads
from utils.logger import get_logger

logger = get_logger("main")
console = Console()


# ── Banner ────────────────────────────────────────────────────
def print_banner():
    """Print the startup banner with branding."""
    console.print()
    console.print(Panel.fit(
        "[bold magenta]╔═══════════════════════════════════════════╗[/bold magenta]\n"
        "[bold magenta]║     ASTRAQUOTE LEAD ENGINE                ║[/bold magenta]\n"
        "[bold magenta]║     Swiss B2B Lead Generation System      ║[/bold magenta]\n"
        "[bold magenta]╚═══════════════════════════════════════════╝[/bold magenta]\n\n"
        f"[cyan]Target:[/cyan]  Plumbing / HVAC / Sanitaire businesses\n"
        f"[cyan]Cantons:[/cyan] {', '.join(config.TARGET_CANTONS)}\n"
        f"[cyan]Goal:[/cyan]   {config.TARGET_LEAD_COUNT} qualified leads with deep research\n"
        f"[cyan]Engine:[/cyan] Rule-based public-info research (no AI/LLM)\n\n"
        f"[dim]Dashboard → {config.DASHBOARD_URL}[/dim]\n"
        f"[dim]Built by Evolnex.digital[/dim]",
        border_style="magenta",
        padding=(1, 4),
    ))
    console.print()


# ── Config Validation ─────────────────────────────────────────
def validate_config() -> list[str]:
    """Validate that all required configuration is set."""
    errors = []

    if not config.TARGET_CANTONS:
        errors.append("TARGET_CANTONS is empty in config.py")

    if not config.PRIMARY_NICHES:
        errors.append("PRIMARY_NICHES is empty in config.py")

    if config.TARGET_LEAD_COUNT < 1:
        errors.append("TARGET_LEAD_COUNT must be >= 1")

    if config.MIN_EMPLOYEES < 1:
        errors.append("MIN_EMPLOYEES must be >= 1")

    return errors


# ── Pipeline Orchestrator ─────────────────────────────────────
async def run_pipeline() -> dict:
    """
    Run the full pipeline:
      L1: Discovery (210+ raw leads)
      L2: Region & Size Filter
      L3-L6 (merged research/enrich/final-gate loop): research and enrich
           candidates, adaptively re-crawling for more raw material, until
           config.TARGET_LEAD_COUNT leads meet ALL THREE hard requirements —
           a valid phone, a real named contact, and research that actually
           completed (not the timeout/crash fallback) — or the search space
           is genuinely exhausted. Only the best TARGET_LEAD_COUNT by fit
           score are kept as the delivered set; every other candidate that
           was actually processed is marked status='rejected' with why,
           never silently dropped.
      L7: Dashboard Generation
    """
    from layers.layer1_discovery import discover_accounts, normalize_name
    from layers.layer2_filter import batch_filter
    from layers.layer3_gate import select_top
    from layers.layer4_recrawl import recrawl
    from layers.layer5_research import batch_research
    from layers.layer6_enrich import batch_enrich
    from layers.layer7_dashboard import refresh_dashboard_data

    from utils.state_manager import update_state, check_cancellation, PipelineCancelled
    from utils.database import insert_lead, update_lead, add_to_blacklist, start_new_run
    from utils.scoring import compute_fit_score, is_weak_inferred_guess
    from utils.company_size import passes_min_size

    # Every run starts from a clean slate: old leads are backed up then wiped
    # so the dashboard never accumulates stale batches from past runs — only
    # the blacklist (untouched by this) remembers what's already been
    # assessed, so a wiped-out company is never rediscovered as if new.
    run_id = start_new_run()

    def _name_key(lead: dict) -> str:
        return normalize_name(lead.get("company_name", ""))

    FINAL_TARGET = config.TARGET_LEAD_COUNT

    def _is_final_ready(lead: dict) -> bool:
        """The hard bar for the delivered set — ALL FOUR must hold:
          1. a valid phone (already required to reach here),
          2. a named contact of any tier EXCEPT a bare-surname-only guess with
             no first name and no independent confirmation (see
             utils.scoring.is_weak_inferred_guess) — live user review found
             those (e.g. "Balmelli SA" -> "Balmelli") indistinguishable from a
             brand name, not a real callable contact. A 2-3 token guess like
             "Bally Louis" from "Bally Louis & Fils SA" still passes.
          3. research that actually completed (not the timeout/crash fallback),
          4. a company-size band big enough per config.MIN_COMPANY_SIZE_BAND —
             this is what keeps one/two-person shops out of the final list."""
        return (bool(lead.get("phone"))
                and bool(lead.get("decision_maker"))
                and not is_weak_inferred_guess(lead)
                and bool(lead.get("research_complete"))
                and passes_min_size(lead.get("size_band") or "unknown"))

    stats = {
        "discovered": 0,
        "after_filter": 0,
        "candidates_processed": 0,
        "final_ready": 0,
        "qualified": 0,
        "researched": 0,
        "enriched": 0,
        "recrawl_iterations": 0,
        "started_at": datetime.now().isoformat(),
    }

    update_state({
        "status": "running",
        "current_layer": 1,
        "current_layer_name": "Discovery",
        "target_lead_count": FINAL_TARGET,
        "leads_discovered": 0,
        "leads_filtered": 0,
        "leads_qualified": 0,
        "leads_researched": 0,
        "leads_enriched": 0,
        "last_log": "Starting wide-net discovery..."
    })

    # ── LAYER 1: Discovery ────────────────────────────────────
    console.print("\n[bold cyan]━━━ LAYER 1: DISCOVERY ━━━[/bold cyan]")
    console.print(f"[dim]Target: {config.DISCOVERY_TARGET}+ raw leads across {len(config.TARGET_CANTONS)} cantons[/dim]\n")

    check_cancellation()
    raw_leads = await discover_accounts()
    stats["discovered"] = len(raw_leads)
    update_state({
        "leads_discovered": len(raw_leads),
        "last_log": f"Layer 1 complete: {len(raw_leads)} raw leads discovered."
    })

    console.print(f"\n[green]✓ Layer 1 complete:[/green] {len(raw_leads)} raw leads discovered\n")

    if not raw_leads:
        update_state({"status": "idle", "last_log": "Pipeline stopped: No leads discovered."})
        console.print("[red]✗ No leads found. Check your internet connection and config.[/red]")
        return stats

    # ── LAYER 2: Filter ───────────────────────────────────────
    update_state({
        "current_layer": 2,
        "current_layer_name": "Filter",
        "last_log": "Filtering by canton, phone, and niche relevance..."
    })
    console.print("[bold cyan]━━━ LAYER 2: REGION & SIZE FILTER ━━━[/bold cyan]")
    console.print(f"[dim]Filtering by canton, phone, niche relevance...[/dim]\n")

    check_cancellation()
    passed, eliminated = batch_filter(raw_leads)
    stats["after_filter"] = len(passed)
    update_state({
        "leads_filtered": len(passed),
        "last_log": f"Layer 2 complete: {len(passed)} passed, {len(eliminated)} eliminated."
    })

    console.print(f"[green]✓ Layer 2 complete:[/green] {len(passed)} passed / {len(eliminated)} eliminated\n")

    # ── LAYERS 3-6: Research, Enrich & Final Gate ─────────────
    # Attrition (no contact discoverable, research timing out, or the business
    # turning out to be too small once we can size it) means processing exactly
    # FINAL_TARGET candidates would deliver FEWER than FINAL_TARGET usable
    # leads — that gap is what this loop closes, by adaptively pulling in more
    # raw material until enough candidates actually clear every requirement.
    console.print("[bold cyan]━━━ LAYERS 3-6: RESEARCH, ENRICH & FINAL GATE ━━━[/bold cyan]")
    console.print(f"[dim]Target: {FINAL_TARGET} final leads, each with a valid phone, a named "
                  f"contact, completed research, and an estimated size of at least "
                  f"'{config.MIN_COMPANY_SIZE_BAND}' (≈ a real small team, not a one-person shop)[/dim]\n")

    def _dedup_against(leads: list, existing_phones: set, existing_names: set) -> list:
        """Keep only leads whose phone AND normalized name are both new,
        updating the two sets in place — so within-`leads` duplicates are
        caught too, not just duplicates against what was already in the sets.
        Defense in depth: Layer 1's own discovery-time dedup should already
        catch same-name-different-phone duplicates, but this doesn't assume
        that held — every batch entering the candidate pool is re-checked here."""
        kept = []
        for lead in leads:
            phone, nk = lead.get("phone"), _name_key(lead)
            if phone in existing_phones:
                continue
            if nk and nk in existing_names:
                continue
            if phone:
                existing_phones.add(phone)
            if nk:
                existing_names.add(nk)
            kept.append(lead)
        return kept

    candidate_pool: list = _dedup_against(passed, set(), set())
    processed_phones: set = set()
    all_enriched: list = []
    final_ready: list = []
    used_queries: set = set()
    used_combos: set = set()
    iteration = 0

    while True:
        check_cancellation()
        to_process = [l for l in candidate_pool if l.get("phone") not in processed_phones]

        if to_process:
            # Ranked by data-completeness so the most promising candidates in
            # this batch are the ones concurrency slots pick up first.
            to_process = select_top(to_process, len(to_process))

            update_state({
                "current_layer": 3,
                "current_layer_name": "Qualify & Research",
                "last_log": f"Processing {len(to_process)} candidates toward the {FINAL_TARGET}-lead target..."
            })
            for lead in to_process:
                lead["status"] = "qualified"
                lead["layer_reached"] = 4
                lead["run_id"] = run_id
                insert_lead(lead)
            processed_phones.update(l.get("phone") for l in to_process)
            stats["candidates_processed"] += len(to_process)

            update_state({
                "current_layer": 5,
                "current_layer_name": "Deep Research",
                "last_log": f"Researching {len(to_process)} candidates..."
            })
            console.print(f"\n[cyan]Researching {len(to_process)} candidates...[/cyan]")
            researched = await batch_research(to_process)
            stats["researched"] += len(researched)
            update_state({"leads_researched": stats["researched"]})
            console.print(f"[green]✓[/green] {len(researched)} researched\n")

            update_state({
                "current_layer": 6,
                "current_layer_name": "Enrichment",
                "last_log": f"Enriching {len(researched)} candidates..."
            })
            console.print(f"[cyan]Enriching {len(researched)} candidates...[/cyan]")
            enriched = await batch_enrich(researched)
            stats["enriched"] += len(enriched)
            update_state({"leads_enriched": stats["enriched"]})
            console.print(f"[green]✓[/green] {len(enriched)} enriched\n")

            all_enriched.extend(enriched)
            newly_ready = [l for l in enriched if _is_final_ready(l)]
            final_ready.extend(newly_ready)

            console.print(f"  → {len(newly_ready)}/{len(enriched)} in this batch met the final bar "
                          f"(phone + named contact + completed research + big enough). "
                          f"Total so far: {len(final_ready)}/{FINAL_TARGET}\n")

        if len(final_ready) >= FINAL_TARGET:
            console.print(f"[green]✓ Final target reached: {len(final_ready)}/{FINAL_TARGET} leads "
                          f"meet every requirement.[/green]\n")
            break

        if iteration >= config.MAX_RECRAWL_ITERATIONS:
            console.print(f"[yellow]⚠ Hit the re-crawl iteration cap ({config.MAX_RECRAWL_ITERATIONS}) "
                          f"with {len(final_ready)}/{FINAL_TARGET} final leads.[/yellow]\n")
            break

        iteration += 1
        stats["recrawl_iterations"] = iteration
        update_state({
            "current_layer": 4,
            "current_layer_name": "Re-Crawl",
            "last_log": f"Only {len(final_ready)}/{FINAL_TARGET} final leads so far. "
                        f"Re-crawl iteration {iteration}/{config.MAX_RECRAWL_ITERATIONS}..."
        })
        console.print(f"[bold cyan]━━━ LAYER 4: ADAPTIVE RE-CRAWL (iteration {iteration}) ━━━[/bold cyan]")
        console.print(f"  Only {len(final_ready)}/{FINAL_TARGET} final leads so far — expanding search...")

        check_cancellation()
        new_raw = await recrawl(candidate_pool, iteration, used_queries, used_combos)
        if not new_raw:
            console.print("[yellow]⚠ Search space exhausted — no new candidates found this iteration. "
                          "Stopping early rather than spinning further.[/yellow]\n")
            break

        new_passed, _ = batch_filter(new_raw)
        # Dedup against the WHOLE pool by phone AND by normalized name — a
        # company already in the pool under a different phone number must not
        # be added again as an apparent second candidate.
        existing_phones = {l.get("phone") for l in candidate_pool if l.get("phone")}
        existing_names = {_name_key(l) for l in candidate_pool if l.get("company_name")}
        existing_names.discard("")
        new_passed = _dedup_against(new_passed, existing_phones, existing_names)

        if not new_passed:
            # NOT the same as "search exhausted": recrawl() DID return fresh
            # material (new_raw was non-empty, or we wouldn't be here), it just
            # didn't survive Layer 2 filtering or turned out to all be
            # duplicates of companies already in the pool. used_queries/
            # used_combos already exclude what was just tried, so the NEXT
            # iteration draws genuinely different territory — loop again
            # instead of giving up on a single unlucky batch.
            console.print(f"  [dim](All {len(new_raw)} candidates from this iteration were filtered out "
                          f"or already known — trying a fresh batch next iteration.)[/dim]\n")
        else:
            candidate_pool.extend(new_passed)
            console.print(f"  → {len(new_passed)} new candidates to research\n")

    # Rank by fit score first so the dedup pass below keeps the BETTER-scoring
    # entry when the same company appears twice under different phone numbers.
    final_ready.sort(key=lambda l: compute_fit_score(l)["score"], reverse=True)

    # Final safety net: collapse same-company-different-phone duplicates that
    # slipped past the earlier per-source checks (defense in depth — this is
    # the one guarantee that "no duplicates" holds regardless of where an
    # upstream check might have a gap). Iterating best-first means the first
    # lead seen per company is the highest fit-scoring one, so it's the one kept.
    duplicate_reasons: dict = {}
    seen_name_keys: dict = {}
    deduped_final_ready: list = []
    for lead in final_ready:
        key = _name_key(lead) or lead.get("phone")
        winner = seen_name_keys.get(key)
        if winner is not None:
            phone = lead.get("phone")
            if phone:
                duplicate_reasons[phone] = (
                    f"Duplicate of {winner.get('company_name')} (same company, different phone "
                    f"number) — kept the higher fit-scoring entry"
                )
            continue
        seen_name_keys[key] = lead
        deduped_final_ready.append(lead)
    final_ready = deduped_final_ready

    # Keep ALL surviving qualified leads that cleared hard filters (no artificial cap)
    qualified = final_ready
    final_phones = {l.get("phone") for l in qualified}

    if duplicate_reasons:
        console.print(f"[dim]  ({len(duplicate_reasons)} duplicate entries for a company already "
                      f"in the list were collapsed — see 'rejected' leads for details.)[/dim]\n")

    excluded_too_small = 0
    for lead in all_enriched:
        phone = lead.get("phone")
        if not phone or phone in final_phones:
            continue
        if phone in duplicate_reasons:
            reason = duplicate_reasons[phone]
        elif not lead.get("decision_maker"):
            reason = "No named contact found — excluded from the final list"
        elif is_weak_inferred_guess(lead):
            reason = (f"Contact \"{lead.get('decision_maker')}\" is only a bare surname guessed from the "
                      f"company name, with no first name or independent confirmation — too weak to call a "
                      f"named contact, excluded from the final list")
        elif not lead.get("research_complete"):
            reason = "Research timed out/incomplete — excluded from the final list"
        elif not passes_min_size(lead.get("size_band") or "unknown"):
            reason = (f"Company too small — estimated {lead.get('employees_estimate') or 'size unverifiable'} "
                      f"(band '{lead.get('size_band') or 'unknown'}', below the '{config.MIN_COMPANY_SIZE_BAND}' "
                      f"minimum) — excluded from the final list")
            excluded_too_small += 1
        else:
            reason = "Excluded by hard filter criteria"
        update_lead(phone, {"status": "rejected", "elimination_reasons": reason})


    stats["final_ready"] = len(final_ready)
    stats["qualified"] = len(qualified)
    stats["excluded_too_small"] = excluded_too_small
    update_state({
        "leads_qualified": len(qualified),
        "last_log": f"Final gate complete: {len(qualified)}/{FINAL_TARGET} leads "
                    f"(phone + named contact + completed research + big enough)."
    })
    console.print(f"[green]✓ {len(qualified)} final leads ready[/green] — all with a phone, a named "
                  f"contact, completed research, and an estimated size ≥ '{config.MIN_COMPANY_SIZE_BAND}'\n")
    if excluded_too_small:
        console.print(f"[dim]  ({excluded_too_small} otherwise-complete leads were set aside as too small "
                      f"— see them by filtering status='rejected' in the dashboard.)[/dim]\n")

    # Every candidate fully enriched this run — winner or not — goes on the
    # blacklist so a future run never re-scrapes or re-contacts it, by BOTH
    # phone and normalized name — the name key is what lets a future run
    # recognize this same company even if it later surfaces under a different
    # phone number (e.g. the owner's mobile instead of the shop landline).
    for lead in all_enriched:
        if lead.get("phone"):
            add_to_blacklist(lead["phone"], lead.get("company_name", ""), _name_key(lead))

    # ── LAYER 7: Dashboard ────────────────────────────────────
    update_state({
        "current_layer": 7,
        "current_layer_name": "Dashboard",
        "last_log": "Refreshing dashboard data..."
    })
    console.print("[bold cyan]━━━ LAYER 7: DASHBOARD GENERATION ━━━[/bold cyan]")

    check_cancellation()
    refresh_dashboard_data()

    update_state({
        "status": "completed",
        "last_log": "Pipeline execution completed successfully."
    })
    console.print(f"[green]✓ Dashboard ready at {config.DASHBOARD_URL}[/green]\n")

    stats["completed_at"] = datetime.now().isoformat()
    return stats


def reconcile_and_finalize_run(run_id: str) -> dict:
    """Re-runs the same keep-the-best-N / demote-the-rest reconciliation that
    run_pipeline() normally does right after its adaptive loop — but reading
    straight from the DB instead of in-memory lists, so it also works when
    called after the fact.

    This exists because a pipeline stopped mid-run (PipelineCancelled, raised
    by check_cancellation() and caught in dashboard/app.py's
    run_background_pipeline(), well outside run_pipeline()'s own call frame)
    skips that reconciliation entirely — every lead that had reached Layer 6
    is left sitting as whatever status it last had, with no distinction
    between "met every requirement" and "researched but incomplete/no
    contact/too small". Call this once after catching that cancellation to
    put the DB back into the same consistent state a normal completion would
    have produced, instead of requiring manual DB surgery each time."""
    from utils.database import get_connection, add_to_blacklist
    from utils.scoring import compute_fit_score, is_weak_inferred_guess
    from utils.company_size import passes_min_size
    from layers.layer1_discovery import normalize_name

    def is_final_ready(lead: dict) -> bool:
        return (bool(lead.get("phone"))
                and bool(lead.get("decision_maker"))
                and not is_weak_inferred_guess(lead)
                and bool(lead.get("research_complete"))
                and passes_min_size(lead.get("size_band") or "unknown"))

    def name_key(lead: dict) -> str:
        return normalize_name(lead.get("company_name", ""))

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM leads WHERE run_id = ? AND status != 'rejected'", (run_id,)
        ).fetchall()
        all_enriched = [dict(r) for r in rows]
        if not all_enriched:
            return {"reconciled": False, "reason": "no non-rejected leads for this run_id"}

        final_ready = [l for l in all_enriched if is_final_ready(l)]
        final_ready.sort(key=lambda l: (l.get("fit_score") or compute_fit_score(l)["score"]), reverse=True)

        seen_keys: dict = {}
        deduped: list = []
        duplicate_reasons: dict = {}
        for lead in final_ready:
            key = name_key(lead) or lead.get("phone")
            winner = seen_keys.get(key)
            if winner is not None:
                phone = lead.get("phone")
                if phone:
                    duplicate_reasons[phone] = (
                        f"Duplicate of {winner.get('company_name')} (same company, different phone "
                        f"number) — kept the higher fit-scoring entry"
                    )
                continue
            seen_keys[key] = lead
            deduped.append(lead)
        final_ready = deduped

        qualified = final_ready[:config.TARGET_LEAD_COUNT]
        final_phones = {l.get("phone") for l in qualified}

        demoted = 0
        for lead in all_enriched:
            phone = lead.get("phone")
            if not phone or phone in final_phones:
                continue
            if phone in duplicate_reasons:
                reason = duplicate_reasons[phone]
            elif not lead.get("decision_maker"):
                reason = "No named contact found — excluded from the final list"
            elif not lead.get("research_complete"):
                reason = "Research timed out/incomplete — excluded from the final list"
            elif not passes_min_size(lead.get("size_band") or "unknown"):
                reason = (f"Company too small — estimated {lead.get('employees_estimate') or 'size unverifiable'} "
                          f"(band '{lead.get('size_band') or 'unknown'}', below the '{config.MIN_COMPANY_SIZE_BAND}' "
                          f"minimum) — excluded from the final list")
            else:
                reason = f"Met every requirement but ranked below the top {config.TARGET_LEAD_COUNT} by fit score"
            conn.execute(
                "UPDATE leads SET status = 'rejected', elimination_reasons = ? WHERE phone = ? AND run_id = ?",
                (reason, phone, run_id),
            )
            demoted += 1

        for lead in qualified:
            conn.execute(
                "UPDATE leads SET status = 'enriched' WHERE phone = ? AND run_id = ?",
                (lead.get("phone"), run_id),
            )
        conn.commit()

        # Same as a normal completion: every fully-processed lead (delivered or
        # not) goes on the blacklist so a future run never re-researches it.
        for lead in all_enriched:
            if lead.get("phone"):
                add_to_blacklist(lead["phone"], lead.get("company_name", ""), name_key(lead))

        return {"reconciled": True, "delivered": len(qualified), "demoted": demoted,
                "total_processed": len(all_enriched)}
    finally:
        conn.close()


# ── Print Summary ─────────────────────────────────────────────
def print_summary(stats: dict):
    """Print a final summary table of the pipeline run."""
    table = Table(title="Pipeline Summary", border_style="cyan", show_lines=True)
    table.add_column("Stage", style="bold white")
    table.add_column("Count", justify="right", style="cyan")

    table.add_row("L1: Discovered", str(stats.get("discovered", 0)))
    table.add_row("L2: After Filter", str(stats.get("after_filter", 0)))
    table.add_row("Candidates Processed", str(stats.get("candidates_processed", 0)))
    table.add_row("L5: Researched", str(stats.get("researched", 0)))
    table.add_row("L6: Enriched", str(stats.get("enriched", 0)))
    if stats.get("excluded_too_small"):
        table.add_row("Excluded: Too Small", str(stats["excluded_too_small"]))
    table.add_row("Met Final Bar (phone+name+research+size)", str(stats.get("final_ready", 0)))
    table.add_row("Final Delivered", str(stats.get("qualified", 0)))

    if stats.get("recrawl_iterations", 0) > 0:
        table.add_row("Re-crawl Iterations", str(stats["recrawl_iterations"]))

    console.print()
    console.print(table)
    console.print()


# ── CLI Entry Point ───────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="AstraQuote Lead Engine — Swiss B2B Lead Generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  python main.py              Full pipeline run (all 7 layers)
  python main.py --validate   Check config.py is set up correctly
  python main.py --dashboard  Launch dashboard from existing data
  python main.py --export     Export current leads to CSV/Excel
  python main.py --stats      Show database statistics
  python main.py --rescore    Recompute fit_score for existing leads
                              (no network calls — use after a scoring.py change)
        """
    )

    parser.add_argument("--validate", action="store_true",
                        help="Validate configuration only")
    parser.add_argument("--dashboard", action="store_true",
                        help="Launch dashboard from existing data")
    parser.add_argument("--export", action="store_true",
                        help="Export the current delivered batch (status='enriched') to CSV/Excel")
    parser.add_argument("--export-all", action="store_true",
                        help="Like --export, but includes rejected leads too (too small, no "
                             "contact, duplicates, below cutoff) — for audit/debugging")
    parser.add_argument("--stats", action="store_true",
                        help="Show database statistics")
    parser.add_argument("--rescore", action="store_true",
                        help="Recompute fit_score for existing leads using the current "
                             "utils/scoring.py rules (instant, no network calls)")

    args = parser.parse_args()

    # Always print banner
    print_banner()

    # Always init DB
    os.makedirs("data", exist_ok=True)
    os.makedirs("exports", exist_ok=True)
    init_db(config.DB_PATH)

    # ── Validate ──────────────────────────────────────────────
    if args.validate:
        errors = validate_config()
        if errors:
            console.print("[bold red]Configuration Errors:[/bold red]")
            for err in errors:
                console.print(f"  [red]✗[/red] {err}")
            sys.exit(1)
        else:
            console.print("[bold green]✓ Configuration is valid![/bold green]")
            console.print(f"  Research Engine: rule-based (no AI/LLM)")
            console.print(f"  Cantons: {', '.join(config.TARGET_CANTONS)}")
            console.print(f"  Niches: {', '.join(config.PRIMARY_NICHES[:4])}...")
            console.print(f"  Target: {config.TARGET_LEAD_COUNT} leads")
        return

    # ── Dashboard Only ────────────────────────────────────────
    if args.dashboard:
        from layers.layer7_dashboard import launch_dashboard
        launch_dashboard()
        return

    # ── Export ────────────────────────────────────────────────
    if args.export or args.export_all:
        from utils.database import export_leads_csv, export_leads_excel
        include_all = args.export_all
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = f"exports/leads_{timestamp}.csv"
        xlsx_path = f"exports/leads_{timestamp}.xlsx"
        export_leads_csv(csv_path, include_all=include_all)
        export_leads_excel(xlsx_path, include_all=include_all)
        console.print(f"[green]✓ Exported to:[/green]")
        console.print(f"  CSV:   {csv_path}")
        console.print(f"  Excel: {xlsx_path}")
        if include_all:
            console.print("[dim]  (--export-all: includes rejected leads too — too small, no "
                          "contact, duplicates, below cutoff)[/dim]")
        else:
            console.print("[dim]  Current delivered batch only (status='enriched'). "
                          "Use --export-all to include rejected leads too.[/dim]")
        return

    # ── Rescore ──────────────────────────────────────────────
    # compute_fit_score is a pure function over fields already in the DB (legal
    # form, Zefix status, digital signals, niche, decision-maker) — no network
    # calls — so scoring-rule changes (weights, contact-tier logic, etc.) can be
    # applied to leads already researched/enriched without re-running Layers 1-6.
    # This does NOT re-run decision-maker discovery itself — a lead that never
    # had a name found still won't have one after this; only a real Layer 6
    # re-enrichment (or a fresh pipeline run) can improve on that.
    if args.rescore:
        from utils.database import get_leads, update_lead
        from utils.scoring import compute_fit_score

        leads = get_leads(layer=5)  # anything that reached Layer 5+ has the fields fit_score needs
        if not leads:
            console.print("[yellow]No researched/enriched leads found to rescore.[/yellow]")
            return

        changed = 0
        newly_qualified = 0
        newly_unqualified = 0
        for lead in leads:
            old_score = lead.get("fit_score") or 0
            old_qualified = old_score >= 75  # how qualification was judged before this rescore
            fit = compute_fit_score(lead)
            if fit["score"] != old_score:
                changed += 1
            if fit["qualified"] and not old_qualified:
                newly_qualified += 1
            elif old_qualified and not fit["qualified"]:
                newly_unqualified += 1
            if lead.get("phone"):
                update_lead(lead["phone"], {
                    "fit_score": fit["score"],
                    "fit_score_breakdown": json.dumps(fit["breakdown"], ensure_ascii=False),
                })

        console.print(f"[bold green]✓ Rescored {len(leads)} leads.[/bold green]")
        console.print(f"  Score changed on {changed} leads")
        console.print(f"  Newly qualified: {newly_qualified} | Newly unqualified: {newly_unqualified}")
        return

    # ── Stats ────────────────────────────────────────────────
    if args.stats:
        db_stats = get_stats()
        console.print(Panel.fit(
            f"[bold]Database Statistics[/bold]\n\n"
            f"Total leads:    {db_stats.get('total', 0)}\n"
            f"Qualified:      {db_stats.get('qualified', 0)}\n"
            f"Researched:     {db_stats.get('researched', 0)}\n"
            f"Enriched:       {db_stats.get('enriched', 0)}\n"
            f"Rejected:       {db_stats.get('rejected', 0)}\n\n"
            f"By Canton:      {db_stats.get('by_canton', {})}\n"
            f"By Niche:       {db_stats.get('by_niche', {})}",
            border_style="cyan",
        ))
        return

    # ── Full Pipeline ────────────────────────────────────────
    errors = validate_config()
    if errors:
        console.print("[bold red]Fix these config errors first:[/bold red]")
        for err in errors:
            console.print(f"  [red]✗[/red] {err}")
        console.print("\n[dim]Run: python main.py --validate[/dim]")
        sys.exit(1)

    console.print("[bold green]Starting full 7-layer pipeline...[/bold green]\n")
    start_time = time.time()

    from utils.state_manager import PipelineCancelled
    try:
        stats = asyncio.run(run_pipeline())
        elapsed = time.time() - start_time

        print_summary(stats)

        console.print(Panel.fit(
            f"[bold green]✓ PIPELINE COMPLETE[/bold green]\n\n"
            f"Time: {elapsed:.1f}s ({elapsed/60:.1f} min)\n"
            f"Leads: {stats.get('qualified', 0)}/{config.TARGET_LEAD_COUNT} final "
            f"(phone + named contact + completed research)\n\n"
            f"[cyan]Dashboard → {config.DASHBOARD_URL}[/cyan]\n"
            f"[dim]Run: python main.py --dashboard[/dim]",
            border_style="green",
            padding=(1, 4),
        ))

        # Auto-launch dashboard after pipeline
        from layers.layer7_dashboard import launch_dashboard
        launch_dashboard()

    except PipelineCancelled as e:
        console.print(f"\n[yellow]⚠ {e}[/yellow]")
        sys.exit(0)
    except KeyboardInterrupt:
        console.print("\n[yellow]Pipeline interrupted by user.[/yellow]")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        console.print(f"\n[bold red]✗ Pipeline failed:[/bold red] {e}")
        console.print("[dim]Check data/engine.log for details[/dim]")
        sys.exit(1)


if __name__ == "__main__":
    main()
