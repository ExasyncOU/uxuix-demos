"""
test_export_picklist.py – Testlauf: IDIS Export + Pickliste (max. 3 AROS-Keys).

Lauft im Test-Modus: Nur die ersten TEST_LIMIT AROS-Keys werden verarbeitet.
Ausgabe in K:\\Raussuchlisten\\2026\\
"""

import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

TEST_LIMIT = 3  # Nur die ersten N AROS-Keys verarbeiten

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("test_export_picklist")


async def main():
    from idis_browser import IdisBrowser
    from master_data import MasterData
    from picklist_generator import PicklistGenerator

    browser = IdisBrowser()
    master = MasterData()
    gen = PicklistGenerator(master)

    logger.info("=" * 60)
    logger.info("NACKE TEST: Export + Pickliste (Limit: %d AROS-Keys)", TEST_LIMIT)
    logger.info("=" * 60)

    try:
        # 1. Login
        await browser.login()
        logger.info("Login: OK")

        # 2. Export (heutiges Datum)
        csv_path, rows = await browser.export_orders(date.today(), suffix="test")

        if not rows:
            logger.info("KEINE DATEN HEUTE – Export leer, Testlauf beendet (kein Fehler)")
            return

        logger.info("Export: %d Zeilen aus %s", len(rows), csv_path)

        # 3. Eindeutige AROS-Keys sammeln (Reihenfolge erhalten)
        seen = {}
        for r in rows:
            k = r.get("aros_key", "")
            if k and k not in seen:
                seen[k] = True
        all_keys = list(seen.keys())
        test_keys = all_keys[:TEST_LIMIT]
        test_rows = [r for r in rows if r.get("aros_key") in test_keys]

        logger.info(
            "Gesamt %d AROS-Keys, Test mit ersten %d (%d Zeilen)",
            len(all_keys), len(test_keys), len(test_rows),
        )

        # 4. Picklisten generieren
        output_path = Path(gen.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        logger.info("Ausgabepfad: %s", output_path)

        generated = gen.generate(test_rows, run_date=date.today())

        logger.info("")
        logger.info("ERGEBNIS:")
        for g in generated:
            p = Path(g["filepath"])
            size_kb = p.stat().st_size / 1024 if p.exists() else 0
            logger.info(
                "  OK  %s  (%d Stk, %.1f KB)",
                g["filename"], g["total_qty"], size_kb,
            )

        logger.info("")
        logger.info("TEST ERFOLGREICH – %d Pickliste(n) erstellt", len(generated))

    except Exception as e:
        logger.error("FEHLER: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
