"""
processor.py - GV Overconfirmation v2.0 - Bidirektionale Verarbeitung

Zwei Modi:
  - Bidirektional: TOP (idx 0→N) + BOT (idx N→0) parallel via asyncio.gather
  - Zigzag Fallback: Single Context, alternierend oben/unten
"""

import time

from config import EARLY_STOP_THRESHOLD, REPORT, P, report_error
from overconfirmation import fill_amend_and_save


async def process_direction(page, valid_orders, indices, processed, do_save, label):
    """Verarbeitet Orders in einer Richtung. Stoppt bei Meeting-Point oder Early-Stop.

    Args:
        page: Playwright Page (eigener Context)
        valid_orders: Liste der Orders mit Bundle > 0
        indices: Reihenfolge der Indices (aufsteigend fuer TOP, absteigend fuer BOT)
        processed: Shared set() - Indices die bereits verarbeitet wurden
        do_save: True = Save, False = Dry Run
        label: "TOP" oder "BOT"

    Returns:
        dict: Statistiken (amended, skipped, already_processed, errors, details)
    """
    stats = {
        "amended": 0, "skipped": 0, "already_processed": 0, "errors": 0,
        "amended_details": [], "already_processed_details": [],
    }
    consecutive_already = 0

    for count, i in enumerate(indices):
        # Meeting-Point: anderer Bot hat diesen Index schon verarbeitet
        if i in processed:
            P(f"  [{label}] Index {i} von anderem Bot verarbeitet - STOP")
            break

        # Index als "in Bearbeitung" markieren
        processed.add(i)

        target = valid_orders[i]
        t_order = time.time()
        tag = f"[{label} {count+1}]"

        try:
            # Amend-Button klicken
            amend_sel = f'input[name="mainForm:_idJsp121:{target["idx"]}:_idJsp216"]'
            amend_btn = page.locator(amend_sel)
            if await amend_btn.count() == 0:
                report_error(target["order"], "Amend-Button nicht gefunden", amend_sel)
                stats["errors"] += 1
                P(f"  {tag} {target['order']} - SKIP (kein Amend)")
                continue

            await amend_btn.click()
            await page.wait_for_load_state("networkidle")

            # Overconfirmation + Save + Back
            result = await fill_amend_and_save(page, target["bundle"], do_save)

            changes = result.get("changes", [])
            changed = sum(1 for c in changes if c["delta"] != 0)
            elapsed = time.time() - t_order

            if changed == 0 and len(changes) > 0:
                # Alle Positionen bereits korrekt = already processed
                consecutive_already += 1
                stats["already_processed"] += 1
                stats["already_processed_details"].append({
                    "order": target["order"], "direction": label
                })
                P(f"  {tag} {target['order']:<28} already OK ({consecutive_already}/{EARLY_STOP_THRESHOLD}) {elapsed:.1f}s")

                if consecutive_already >= EARLY_STOP_THRESHOLD:
                    P(f"  [{label}] {EARLY_STOP_THRESHOLD}x consecutive already-processed - STOP")
                    break
            else:
                consecutive_already = 0
                stats["amended"] += 1

                for ch in changes:
                    if ch["delta"] != 0:
                        stats["amended_details"].append({
                            "order": target["order"],
                            "ordered": ch["ordered"],
                            "old_committed": ch["old"],
                            "new_committed": ch["neu"],
                            "delta": ch["delta"],
                            "bundle": target["bundle"],
                            "direction": label,
                        })

                save_mark = "SAVE" if (do_save and changed > 0) else ("dry" if not do_save else "OK")
                P(f"  {tag} {target['order']:<28} B={target['bundle']:<4} "
                  f"{len(changes)}pos {changed}chg [{save_mark}] {elapsed:.1f}s")

        except Exception as e:
            elapsed = time.time() - t_order
            report_error(target["order"], "Exception", str(e)[:120])
            stats["errors"] += 1
            P(f"  {tag} {target['order']} - FEHLER: {str(e)[:60]} {elapsed:.1f}s")

    return stats


async def process_zigzag(page, valid_orders, do_save):
    """Fallback: Verarbeitet Orders abwechselnd von oben und unten in einem Context."""
    P("  [ZIGZAG] Single-Context Modus (abwechselnd oben/unten)")
    processed = set()
    top_idx = 0
    bot_idx = len(valid_orders) - 1
    consecutive_already = 0
    count = 0

    while top_idx <= bot_idx:
        # --- TOP ---
        if top_idx <= bot_idx and top_idx not in processed:
            processed.add(top_idx)
            target = valid_orders[top_idx]
            count += 1
            t_order = time.time()

            try:
                amend_sel = f'input[name="mainForm:_idJsp121:{target["idx"]}:_idJsp216"]'
                amend_btn = page.locator(amend_sel)
                if await amend_btn.count() > 0:
                    await amend_btn.click()
                    await page.wait_for_load_state("networkidle")
                    result = await fill_amend_and_save(page, target["bundle"], do_save)
                    changes = result.get("changes", [])
                    changed = sum(1 for c in changes if c["delta"] != 0)
                    elapsed = time.time() - t_order

                    if changed == 0 and len(changes) > 0:
                        consecutive_already += 1
                        REPORT["total_already_processed"] += 1
                        REPORT["already_processed_details"].append({
                            "order": target["order"], "direction": "TOP"
                        })
                    else:
                        consecutive_already = 0
                        REPORT["total_amended"] += 1
                        for ch in changes:
                            if ch["delta"] != 0:
                                REPORT["amended_details"].append({
                                    "order": target["order"],
                                    "ordered": ch["ordered"],
                                    "old_committed": ch["old"],
                                    "new_committed": ch["neu"],
                                    "delta": ch["delta"],
                                    "bundle": target["bundle"],
                                    "direction": "TOP",
                                })

                    save_mark = "SAVE" if (do_save and changed > 0) else "OK"
                    P(f"  [TOP {count}] {target['order']:<28} B={target['bundle']:<4} "
                      f"{changed}chg [{save_mark}] {elapsed:.1f}s")
            except Exception as e:
                report_error(target["order"], "Exception", str(e)[:120])
                REPORT["total_errors"] += 1

            top_idx += 1

        if consecutive_already >= EARLY_STOP_THRESHOLD:
            P(f"  [ZIGZAG] {EARLY_STOP_THRESHOLD}x consecutive already-processed - STOP")
            break

        # --- BOTTOM ---
        if top_idx <= bot_idx and bot_idx not in processed:
            processed.add(bot_idx)
            target = valid_orders[bot_idx]
            count += 1
            t_order = time.time()

            try:
                amend_sel = f'input[name="mainForm:_idJsp121:{target["idx"]}:_idJsp216"]'
                amend_btn = page.locator(amend_sel)
                if await amend_btn.count() > 0:
                    await amend_btn.click()
                    await page.wait_for_load_state("networkidle")
                    result = await fill_amend_and_save(page, target["bundle"], do_save)
                    changes = result.get("changes", [])
                    changed = sum(1 for c in changes if c["delta"] != 0)
                    elapsed = time.time() - t_order

                    if changed == 0 and len(changes) > 0:
                        consecutive_already += 1
                        REPORT["total_already_processed"] += 1
                        REPORT["already_processed_details"].append({
                            "order": target["order"], "direction": "BOT"
                        })
                    else:
                        consecutive_already = 0
                        REPORT["total_amended"] += 1
                        for ch in changes:
                            if ch["delta"] != 0:
                                REPORT["amended_details"].append({
                                    "order": target["order"],
                                    "ordered": ch["ordered"],
                                    "old_committed": ch["old"],
                                    "new_committed": ch["neu"],
                                    "delta": ch["delta"],
                                    "bundle": target["bundle"],
                                    "direction": "BOT",
                                })

                    save_mark = "SAVE" if (do_save and changed > 0) else "OK"
                    P(f"  [BOT {count}] {target['order']:<28} B={target['bundle']:<4} "
                      f"{changed}chg [{save_mark}] {elapsed:.1f}s")
            except Exception as e:
                report_error(target["order"], "Exception", str(e)[:120])
                REPORT["total_errors"] += 1

            bot_idx -= 1

        if consecutive_already >= EARLY_STOP_THRESHOLD:
            P(f"  [ZIGZAG] {EARLY_STOP_THRESHOLD}x consecutive already-processed - STOP")
            break
