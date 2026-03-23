"""
main.py - GV Overconfirmation v2.0 - Pipeline Orchestrator

Orchestriert alle Module: Browser → Login → AROS → Orders → Processing → Report.
Bidirektionaler Modus mit Zigzag-Fallback.

Usage:
  python main.py                                        # Production
  python main.py --dry-run                              # Kein Save
  python main.py --env-file .env.idis735 --cdp-port 9223
"""

import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path

# Encoding Fix fuer Windows (charmap-Crash verhindern)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from config import (
    REPORT, DRY_RUN, IDIS_USER, CDP_PORT, ENV_FILE,
    P, report_warning,
)
from browser import start_browser_detached, create_context
from idis import login_idis, navigate_to_aros
from orders import read_table_full, classify_orders
from processor import process_direction, process_zigzag
from report import push_start_notification, generate_report_html, push_report


async def main():
    t_start = time.time()
    Path("reports").mkdir(exist_ok=True)

    mode_str = "DRY RUN" if DRY_RUN else "PRODUCTION"
    P("")
    P("=" * 65)
    P(f"  GV OVERCONFIRMATION v2.0 - {mode_str}")
    P(f"  User: {IDIS_USER} | Port: {CDP_PORT} | Modular")
    P("=" * 65)

    if not IDIS_USER:
        P(f"  WARNUNG: Credentials leer! Pruefe {ENV_FILE}")
        report_warning(f"IDIS Credentials nicht gesetzt ({ENV_FILE})")

    # --- Browser starten ---
    browser, pw = await start_browser_detached()

    try:
        await _run_pipeline(browser, pw, t_start)
    finally:
        try:
            await pw.stop()
            P("  [Cleanup] Playwright disconnected")
        except Exception:
            pass


async def _run_pipeline(browser, pw, t_start):
    """Hauptpipeline: Login, Bidirektional/Zigzag, Report."""

    # --- Context 1 (TOP bot) ---
    ctx_top, page_top = await create_context(browser)
    login_ok = await login_idis(page_top, "TOP")
    if not login_ok:
        P("  Login fehlgeschlagen - Abbruch")
        await ctx_top.close()
        return

    # --- Start-Benachrichtigung ---
    push_start_notification()

    # --- Navigate TOP to AROS orders ---
    await navigate_to_aros(page_top, "TOP")

    # --- Order-Liste lesen ---
    orders = await read_table_full(page_top)
    P(f"  {len(orders)} Orders geladen")
    REPORT["total_orders"] = len(orders)

    if not orders:
        P("  Keine Orders - fertig")
        REPORT["duration_seconds"] = round(time.time() - t_start, 1)
        html = generate_report_html()
        push_report(html)
        await ctx_top.close()
        return

    # --- Orders klassifizieren ---
    valid_orders = classify_orders(orders)

    P(f"  Zu verarbeiten: {len(valid_orders)} | Skipped: {REPORT['total_skipped']}")

    if not valid_orders:
        P("  Keine Orders mit Bundle > 0 - fertig")
        REPORT["duration_seconds"] = round(time.time() - t_start, 1)
        html = generate_report_html()
        push_report(html)
        await ctx_top.close()
        return

    do_save = not DRY_RUN
    N = len(valid_orders)

    # --- Bidirektional versuchen (2 Contexts) ---
    bidirectional = False
    ctx_bot = None
    page_bot = None

    try:
        ctx_bot, page_bot = await create_context(browser)
        login_ok_bot = await login_idis(page_bot, "BOT")
        if login_ok_bot:
            await navigate_to_aros(page_bot, "BOT")
            bidirectional = True
            P(f"  Bidirektional aktiv: TOP (0->{N-1}) + BOT ({N-1}->0)")
        else:
            P(f"  BOT Login fehlgeschlagen - Fallback auf Zigzag")
            await ctx_bot.close()
            ctx_bot = None
    except Exception as e:
        P(f"  Zweiter Context fehlgeschlagen: {str(e)[:60]}")
        P(f"  Fallback auf Zigzag-Modus")
        if ctx_bot:
            try:
                await ctx_bot.close()
            except Exception:
                pass
            ctx_bot = None

    REPORT["bidirectional"] = bidirectional

    # --- Verarbeitung ---
    if bidirectional:
        processed = set()

        top_indices = list(range(N))
        bot_indices = list(range(N - 1, -1, -1))

        P(f"\n  === BIDIREKTIONAL START ===")

        top_stats, bot_stats = await asyncio.gather(
            process_direction(page_top, valid_orders, top_indices, processed, do_save, "TOP"),
            process_direction(page_bot, valid_orders, bot_indices, processed, do_save, "BOT"),
        )

        # Merge stats
        for stats in [top_stats, bot_stats]:
            REPORT["total_amended"] += stats["amended"]
            REPORT["total_already_processed"] += stats["already_processed"]
            REPORT["total_errors"] += stats["errors"]
            REPORT["amended_details"].extend(stats["amended_details"])
            REPORT["already_processed_details"].extend(stats["already_processed_details"])

        P(f"\n  === BIDIREKTIONAL FERTIG ===")
        P(f"  TOP: {top_stats['amended']} amended, {top_stats['already_processed']} already")
        P(f"  BOT: {bot_stats['amended']} amended, {bot_stats['already_processed']} already")

    else:
        # Zigzag Fallback
        await process_zigzag(page_top, valid_orders, do_save)

    # --- Report ---
    REPORT["duration_seconds"] = round(time.time() - t_start, 1)

    P("")
    P("=" * 65)
    P("  REPORT")
    P("=" * 65)
    P(f"  Datum:        {date.today()}")
    P(f"  User:         {IDIS_USER}")
    P(f"  Modus:        {'DRY RUN' if DRY_RUN else 'PRODUCTION'} | {'Bidirektional' if bidirectional else 'Zigzag'}")
    P(f"  Dauer:        {REPORT['duration_seconds']:.1f}s")
    P(f"  Orders total: {REPORT['total_orders']}")
    P(f"  Verarbeitet:  {REPORT['total_amended']}")
    P(f"  Already OK:   {REPORT['total_already_processed']}")
    P(f"  Skipped:      {REPORT['total_skipped']}")
    P(f"  Fehler:       {REPORT['total_errors']}")

    if REPORT["amended_details"]:
        P("\n  HOCHGESETZTE ORDERS:")
        for a in REPORT["amended_details"]:
            P(f"    {a['order']:30s} [{a.get('direction','')}] "
              f"Bestellt={a['ordered']:>5}  Alt={a['old_committed']:>5}  "
              f"Neu={a['new_committed']:>5}  Delta=+{a['delta']:<4}  Bundle={a['bundle']}")

    if REPORT["errors"]:
        P("\n  FEHLER:")
        for e in REPORT["errors"]:
            P(f"    {e['order']}: {e['reason']} - {e.get('details', '')}")

    if REPORT["warnings"]:
        P(f"\n  WARNUNGEN ({len(REPORT['warnings'])}):")
        for w in REPORT["warnings"]:
            P(f"    - {w}")

    # Report-Dateien
    report_date = date.today().strftime("%Y-%m-%d")
    with open(f"reports/report_{report_date}_{IDIS_USER}.json", "w", encoding="utf-8") as f:
        json.dump(REPORT, f, indent=2, ensure_ascii=False)
    P(f"\n  JSON: reports/report_{report_date}_{IDIS_USER}.json")

    html = generate_report_html()
    with open(f"reports/report_{report_date}_{IDIS_USER}.html", "w", encoding="utf-8") as f:
        f.write(html)
    P(f"  HTML: reports/report_{report_date}_{IDIS_USER}.html")

    push_report(html)

    # --- Cleanup ---
    P("\n" + "=" * 65)
    P("  Pipeline abgeschlossen.")
    P("=" * 65)

    try:
        await ctx_top.close()
    except Exception:
        pass
    if ctx_bot:
        try:
            await ctx_bot.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
