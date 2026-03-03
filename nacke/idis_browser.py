"""
idis_browser.py – Playwright-basierte IDIS-Automation.

Funktionen:
  - login() → IDIS Mailbox 729 einloggen
  - export_orders(date) → Filter aktueller Tag → Select All → Export List → CSV
  - get_result_table_data() → Extrahiert Order-Daten aus der Result-Tabelle
  - apply_amendments(amendments) → Für jede Order: Amend → neue Menge → Speichern
  - Archiviert jeden Export als IDIS_EXPORT_YYYY-MM-DD_pre.csv / _post.csv
  - Screenshot bei Fehler

Selektoren: Verifiziert 2026-02-23 via Playwright DOM-Analyse (Table #24, 439 rows).
"""

import asyncio
import csv
import json
import logging
import os
import subprocess
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# .env laden
load_dotenv()


class IdisBrowser:
    """Playwright-Browser-Automation für IDIS."""

    def __init__(self, config_path: str = "config.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)

        idis_cfg = self.cfg.get("idis", {})
        self.url = idis_cfg.get("url", "")
        self.mailbox = idis_cfg.get("mailbox", "729")
        self.timeout = idis_cfg.get("timeout_ms", 30000)
        self.screenshot_on_error = idis_cfg.get("screenshot_on_error", True)

        self.username = os.getenv("IDIS_USERNAME", "")
        self.password = os.getenv("IDIS_PASSWORD", "")

        self.exports_dir = Path(self.cfg["paths"]["exports_dir"])
        self.exports_dir.mkdir(parents=True, exist_ok=True)

        self._browser = None
        self._page = None

    # ------------------------------------------------------------------
    # Browser-Lifecycle
    # ------------------------------------------------------------------

    async def _ensure_browser(self):
        """Verbindet per CDP mit bestehendem Browser oder startet neuen.

        CDP-Pattern (PFLICHT):
        1. Versuche bestehende Session auf Port 9222 zu verbinden.
        2. Falls nicht verfügbar: Browser als eigener Prozess starten (detached).
        3. NIEMALS chromium.launch() – blockiert den Worker.
        4. NIEMALS slow_mo – volle Geschwindigkeit.
        5. NIEMALS bestehende Contexts/Pages schliessen.
        """
        if self._browser is not None:
            return

        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        chromium_path = self._pw.chromium.executable_path
        chrome_data = str(Path("chrome_data").absolute())

        # Versuche bestehende CDP-Session wiederzuverwenden
        try:
            self._browser = await self._pw.chromium.connect_over_cdp(
                "http://localhost:9222", timeout=3000
            )
            logger.info("CDP: bestehende Browser-Session wiederverwendet")
        except Exception:
            # Browser als eigener Prozess starten (detached, non-blocking)
            logger.info("CDP: Starte neuen Browser auf Port 9222...")
            subprocess.Popen(
                [
                    chromium_path,
                    "--remote-debugging-port=9222",
                    f"--user-data-dir={chrome_data}",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            await asyncio.sleep(2)
            self._browser = await self._pw.chromium.connect_over_cdp("http://localhost:9222")
            logger.info("CDP: Browser gestartet und verbunden (Port 9222)")

        # Neuen Context erstellen (NIEMALS bestehende Contexts/Pages schliessen!)
        self._context = await self._browser.new_context(
            viewport={"width": 1400, "height": 900},
            ignore_https_errors=True,
        )
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.timeout)
        logger.info("Browser bereit (CDP, sichtbar, Port 9222)")

    async def close(self):
        """Playwright-Verbindung trennen. Browser bleibt offen (CDP-Pattern)."""
        if hasattr(self, "_context") and self._context:
            await self._context.close()
            self._context = None
        # KEINE browser.close() – Browser bleibt für nächsten Run offen
        self._browser = None
        if hasattr(self, "_pw") and self._pw:
            await self._pw.stop()
            self._pw = None
        logger.info("Playwright-Verbindung getrennt (Browser läuft weiter)")

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # IDIS JSF Selektoren (ermittelt 2026-02-20, aktualisiert 2026-02-23)
    # ------------------------------------------------------------------

    # Login
    SEL_LOGIN_USER = 'input[name="j_username"]'
    SEL_LOGIN_PASS = 'input[name="j_password"]'
    SEL_LOGIN_SUBMIT = 'input[type="submit"][name="action"]'

    # Main Menu
    SEL_PROCESS_AROS = 'input[name="mainForm:_idJsp53"]'

    # Filters (Process AROS Orders page)
    SEL_FILTER_IMPORT_DATE = 'select[name="mainForm:importDateFilter"]'
    SEL_FILTER_BATCH = 'select[name="mainForm:batchNumberFilter"]'
    SEL_FILTER_COMPANY = 'select[name="mainForm:companyFilter"]'
    SEL_FILTER_DEST_TYPE = 'select[name="mainForm:destinationTypeFilter"]'
    SEL_FILTER_PACKING = 'select[name="mainForm:packingTypeFilter"]'

    # Action Buttons
    SEL_SHOW_RESULT = 'input[name="mainForm:_idJsp49"]'
    SEL_RESET_FILTER = 'input[name="mainForm:_idJsp48"]'
    SEL_BACK = 'input[name="mainForm:_idJsp246"]'
    SEL_EXPORT_SELECTED = 'input[name="mainForm:_idJsp252"]'
    SEL_CONFIRM_PRINT = 'input[name="mainForm:_idJsp253"]'

    # ------------------------------------------------------------------
    # Amend Form Selectors (verified 2026-02-23)
    # ------------------------------------------------------------------
    # After clicking Amend button, a form with per-destination qty fields appears.
    # Each destination j = 0,1,2,3,4 has two editable fields:
    SEL_AMEND_QTY_COMMITTED_TPL = 'input[name="mainForm:_idJsp109:{j}:_idJsp126"]'  # committed/bundle qty (e.g. 105)
    SEL_AMEND_QTY_PIECES_TPL = 'input[name="mainForm:_idJsp109:{j}:_idJsp140"]'     # pieces qty (e.g. 12, 34, ...)
    # Buttons on the Amend form
    SEL_AMEND_NET_WEIGHT = 'input[name="mainForm:_idJsp98"]'
    SEL_AMEND_BTN_1 = 'input[name="mainForm:_idJsp106"]'      # Amend Quantities
    SEL_AMEND_BTN_2 = 'input[name="mainForm:_idJsp107"]'      # Amend Quantities
    SEL_AMEND_BTN_3 = 'input[name="mainForm:_idJsp108"]'      # Amend Quantities
    SEL_AMEND_SAVE = 'input[name="mainForm:_idJsp155"]'        # Save/Confirm
    SEL_AMEND_CANCEL = 'input[name="mainForm:_idJsp157"]'      # Cancel
    SEL_AMEND_BACK = 'input[name="mainForm:_idJsp159"]'        # Back to list

    # ------------------------------------------------------------------
    # Result Table Selectors (verified 2026-02-23, Table #24, 438 orders)
    # ------------------------------------------------------------------
    # Row CSS classes alternate: row_odd / row_even
    # Each order row index i = 0, 1, 2, ...
    # Row selector templates (replace {i} with row index):
    SEL_ROW_CHECKBOX_TPL = 'input[name="mainForm:_idJsp121:{i}:_idJsp124"]'
    SEL_ROW_AMEND_BTN_TPL = 'input[name="mainForm:_idJsp121:{i}:_idJsp216"]'
    SEL_ROW_SECOND_BTN_TPL = 'input[name="mainForm:_idJsp121:{i}:_idJsp219"]'

    # Result Table Column Indices (0-based, from 30-column header row)
    # Headers: ['', '', 'Order Number', '', '', '', '', '', 'Company', '',
    #           'Priority Flag', '', 'AROS Number', '', 'Order Date', '',
    #           'Import Date', '', 'Item Number', '', 'Picking', '',
    #           'Packing', '', 'Bundle', '', 'Quantity', '', 'Options', '']
    COL_CHECKBOX = 0
    COL_ORDER_NUMBER = 2
    COL_COMPANY = 8
    COL_PRIORITY_FLAG = 10
    COL_AROS_NUMBER = 12
    COL_ORDER_DATE = 14
    COL_IMPORT_DATE = 16
    COL_ITEM_NUMBER = 18
    COL_PICKING = 20
    COL_PACKING = 22
    COL_BUNDLE = 24
    COL_QUANTITY = 26
    COL_OPTIONS = 28

    # Mapping column index to field name for extraction
    RESULT_TABLE_COLUMNS = {
        2: "order_number",
        8: "company",
        10: "priority_flag",
        12: "aros_number",
        14: "order_date",
        16: "import_date",
        18: "item_number",
        20: "picking",
        22: "packing",
        24: "bundle",
        26: "quantity",
    }

    async def login(self) -> bool:
        """Login in IDIS Mailbox 729.

        Returns: True bei Erfolg.
        """
        await self._ensure_browser()

        if not self.username or not self.password:
            raise ValueError(
                "IDIS_USERNAME und IDIS_PASSWORD muessen in .env gesetzt sein"
            )

        try:
            logger.info("IDIS Login: %s (Mailbox %s)", self.url, self.mailbox)
            await self._page.goto(self.url, wait_until="networkidle")

            # JSF Login-Formular
            await self._page.fill(self.SEL_LOGIN_USER, self.username)
            await self._page.fill(self.SEL_LOGIN_PASS, self.password)
            await self._page.click(self.SEL_LOGIN_SUBMIT)
            await self._page.wait_for_load_state("networkidle")
            await self._page.wait_for_timeout(2000)

            # Pruefen ob Main Menu geladen
            title = await self._page.title()
            if "Main Menu" not in title:
                raise RuntimeError(f"Login fehlgeschlagen - Titel: {title}")

            logger.info("IDIS Login erfolgreich (Titel: %s)", title)
            return True

        except Exception as e:
            logger.error("IDIS Login fehlgeschlagen: %s", e)
            await self._screenshot("login_error")
            raise

    async def navigate_to_process_aros(self):
        """Navigiert von Main Menu zu Process AROS Orders."""
        page = self._page
        logger.info("Navigiere zu Process AROS Orders...")
        await page.click(self.SEL_PROCESS_AROS)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)

        title = await page.title()
        if "Process AROS" not in title:
            raise RuntimeError(f"Navigation fehlgeschlagen - Titel: {title}")
        logger.info("Process AROS Orders geladen")

    # ------------------------------------------------------------------
    # Result Table Data Extraction
    # ------------------------------------------------------------------

    async def get_result_table_data(self) -> list[dict]:
        """Extracts order data from the result table after Show Result.

        Reads the DOM table (row_odd / row_even rows), extracts cell text
        using the verified column mapping (COL_* constants).

        Returns:
            List of dicts with keys from RESULT_TABLE_COLUMNS + 'row_index'.
        """
        page = self._page
        orders = []

        # Find all data rows (alternating row_odd / row_even)
        data_rows = page.locator("tr.row_odd, tr.row_even")
        row_count = await data_rows.count()
        logger.info("Result table: %d data rows found", row_count)

        for i in range(row_count):
            row = data_rows.nth(i)
            cells = row.locator("td")
            cell_count = await cells.count()

            order = {"row_index": i}

            for col_idx, field_name in self.RESULT_TABLE_COLUMNS.items():
                if col_idx < cell_count:
                    text = (await cells.nth(col_idx).inner_text()).strip()
                    order[field_name] = text
                else:
                    order[field_name] = ""

            # Only include rows that have an order number
            if order.get("order_number"):
                orders.append(order)

        logger.info("Extracted %d orders from result table", len(orders))
        return orders

    def _find_order_row_index(
        self, orders: list[dict], order_id: str
    ) -> int | None:
        """Finds the row index for an order_id in extracted table data.

        Args:
            orders: List from get_result_table_data()
            order_id: The order number to search for

        Returns:
            Row index (int) or None if not found.
        """
        for order in orders:
            if order.get("order_number") == order_id:
                return order["row_index"]
        return None

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    async def export_orders(
        self, export_date: date, suffix: str = "pre"
    ) -> tuple[str, list[dict]]:
        """Exportiert Orders fuer das angegebene Datum.

        Workflow (mit echten IDIS JSF-Selektoren):
        1. Navigate to Process AROS Orders (falls noch nicht dort)
        2. Filter: Import Date = export_date
        3. Klick "Show Result"
        4. Select All Orders
        5. Klick "Export Selected" -> CSV Download
        6. Archivieren als IDIS_EXPORT_YYYY-MM-DD_{suffix}.csv

        Returns: (csv_path, parsed_rows)
        """
        await self._ensure_browser()
        page = self._page

        try:
            logger.info("IDIS Export: Datum=%s, Suffix=%s", export_date, suffix)

            # Zur Process AROS Orders Seite navigieren (falls noetig)
            title = await page.title()
            if "Process AROS" not in title:
                await self.navigate_to_process_aros()

            # Import Date Filter setzen
            date_str = export_date.strftime("%d.%m.%Y")
            date_select = page.locator(self.SEL_FILTER_IMPORT_DATE)
            # Dropdown: Wert ist das Datum im Format dd.mm.yyyy
            # Pruefen ob Datum als Option vorhanden
            options = await date_select.locator("option").all()
            date_found = False
            for opt in options:
                val = await opt.get_attribute("value") or ""
                txt = (await opt.inner_text()).strip()
                if date_str in val or date_str in txt:
                    await date_select.select_option(value=val)
                    logger.info("Import Date Filter gesetzt: %s", val)
                    date_found = True
                    break

            if not date_found:
                # Alle Daten verwenden und spaeter filtern
                logger.warning(
                    "Datum %s nicht im Filter - verwende 'All Dates'", date_str
                )

            # Show Result klicken
            await page.click(self.SEL_SHOW_RESULT)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)
            await self._screenshot(f"show_result_{suffix}")

            # Pruefen ob Ergebnisse vorhanden (Regel: keine Daten = nichts tun)
            data_rows = page.locator("tr.row_odd, tr.row_even")
            row_count = await data_rows.count()
            if row_count == 0:
                logger.info("Keine Orders fuer %s – Export uebersprungen", date_str)
                return "", []

            logger.info("Ergebnis-Tabelle: %d Zeilen gefunden", row_count)

            # Select All (Checkbox in der Tabellen-Kopfzeile)
            select_all = page.locator(
                'input[type="checkbox"][name*="selectAll"], '
                'input[type="checkbox"]'
            ).first
            try:
                await select_all.click(timeout=5000)
                await page.wait_for_timeout(1000)
                logger.info("Select All geklickt")
            except Exception as e:
                logger.warning("Select All nicht gefunden: %s", e)

            # Export-Flow: Export Selected → (Seite navigiert) → Export List → Download
            # WICHTIG: expect_download MUSS vor dem auslösenden Click gesetzt werden!

            download = None

            # Versuch A: Export Selected löst Download direkt aus (Content-Disposition)
            # Listener muss VOR dem Click aktiv sein
            logger.info("Export Selected: Starte Download-Listener und klicke...")
            try:
                async with page.expect_download(timeout=12000) as dl_info:
                    await page.click(self.SEL_EXPORT_SELECTED)
                download = await dl_info.value
                logger.info("Download via Export Selected: %s", download.suggested_filename)
            except Exception as e:
                logger.info("Kein sofortiger Download nach Export Selected (%s)", type(e).__name__)

            if download is None:
                # Seite analysieren: IDIS navigiert nach Export Selected
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(2000)
                await self._screenshot(f"after_export_selected_{suffix}")

                current_url = page.url
                logger.info("URL nach Export Selected: %s", current_url)

                # Alle Steuerelemente loggen (input, button, a)
                all_elems = []
                for sel in ["input[type='submit']", "input[type='button']", "button", "a"]:
                    items = await page.locator(sel).all()
                    for item in items:
                        try:
                            n = await item.get_attribute("name") or ""
                            v = (await item.get_attribute("value") or
                                 await item.inner_text() or "")
                            t = sel.split("[")[0]
                            all_elems.append(f"{t}:{n}={v[:25]}")
                        except Exception:
                            pass
                logger.info("Steuerelemente nach Export Selected: %s", all_elems[:20])

                # Neue Pages im Context? (IDIS könnte window.open() genutzt haben)
                if len(self._context.pages) > 1:
                    new_page = self._context.pages[-1]
                    logger.info("Neue Page erkannt: %s", new_page.url)
                    try:
                        async with new_page.expect_download(timeout=15000) as dl_info:
                            await new_page.wait_for_load_state("networkidle")
                        download = await dl_info.value
                        logger.info("Download von neuer Page: %s", download.suggested_filename)
                    except Exception:
                        pass

            if download is None:
                # Versuch B: IDIS navigiert nach Export Selected zu /jsf/orderExport.faces
                # Dort ist der "Export List" Button ein <a>-Element (JSF commandLink)
                # Verifizierter Selektor (03.03.2026): a[name="mainForm:header:_idJsp47"]
                for sel in [
                    'a[name="mainForm:header:_idJsp47"]',  # Verifiziert 03.03.2026
                    'a[name*="header:_idJsp"]',             # Flexibler Fallback
                    self.SEL_CONFIRM_PRINT,                 # Fallback: input-Button
                    'input[value*="Export"]',
                    'a[name*="export"]',
                    'a[name*="Export"]',
                ]:
                    try:
                        btn = page.locator(sel)
                        if await btn.is_visible(timeout=3000):
                            logger.info("Export List Element gefunden: %s", sel)
                            async with page.expect_download(timeout=30000) as dl_info:
                                await btn.click()
                            download = await dl_info.value
                            logger.info("Download via Export List: %s",
                                        download.suggested_filename)
                            break
                    except Exception:
                        pass

            if download is None:
                raise RuntimeError(
                    "IDIS Export: Kein Download nach Export Selected + Export List"
                )
            archive_name = (
                f"IDIS_EXPORT_{export_date.strftime('%Y-%m-%d')}_{suffix}.csv"
            )
            archive_path = self.exports_dir / archive_name
            await download.save_as(str(archive_path))

            if archive_path.stat().st_size == 0:
                raise RuntimeError(f"Download leer: {archive_path}")

            logger.info("Export gespeichert: %s (%d bytes)",
                        archive_path, archive_path.stat().st_size)

            rows = self._parse_csv(str(archive_path))
            logger.info("Export enthaelt %d Zeilen", len(rows))

            return str(archive_path), rows

        except Exception as e:
            logger.error("IDIS Export fehlgeschlagen: %s", e)
            await self._screenshot(f"export_error_{suffix}")
            raise

    # ------------------------------------------------------------------
    # Amendments (Overconfirmation)
    # ------------------------------------------------------------------

    async def apply_amendments(
        self, amendments: list[dict], stop_before_save: bool = False
    ) -> int:
        """Wendet Overconfirmation-Amendments in IDIS an.

        Workflow pro Amendment:
        1. Order-Zeile in Result-Tabelle finden (via order_id -> row_index)
        2. Amend-Button klicken (mainForm:_idJsp121:{i}:_idJsp216)
        3. Amend-Formular: neue Menge eingeben (TODO: Formular-Selektoren)
        4. Speichern (oder stoppen wenn stop_before_save=True)

        Args:
            amendments: Liste von Dicts mit:
                - order_id: Order Number (z.B. "73066-200-25-180-009")
                - neu_menge: Neue Menge (int)
                - Optional: size, aros_key, etc. fuer Formular-Felder
            stop_before_save: True = Felder ausfuellen aber NICHT speichern.
                Browser bleibt offen fuer manuelle Verifikation / Discovery.

        Returns:
            Anzahl erfolgreich angewendeter (oder ausgefuellter) Amendments
        """
        await self._ensure_browser()
        page = self._page
        success_count = 0

        # Step 1: Extract table data to map order_id -> row_index
        logger.info("Extracting result table to locate orders...")
        table_orders = await self.get_result_table_data()

        if not table_orders:
            logger.error("Result table is empty - cannot apply amendments")
            await self._screenshot("amend_empty_table")
            return 0

        logger.info(
            "Found %d orders in table, applying %d amendments",
            len(table_orders),
            len(amendments),
        )

        for amend in amendments:
            order_id = amend.get("order_id", "")
            neu_menge = amend.get("neu_menge", 0)

            try:
                logger.info("Amend: Order %s -> %d", order_id, neu_menge)

                # Step 2: Find row index for this order
                row_idx = self._find_order_row_index(table_orders, order_id)
                if row_idx is None:
                    logger.error(
                        "  Order %s nicht in Tabelle gefunden - ueberspringe",
                        order_id,
                    )
                    continue

                # Step 3: Click the Amend button for this row
                # Verified selector: mainForm:_idJsp121:{i}:_idJsp216
                amend_name = self.SEL_ROW_AMEND_BTN_TPL.replace(
                    "{i}", str(row_idx)
                )
                # Extract just the name value from the template
                amend_name = amend_name.split('"')[1] if '"' in amend_name else amend_name
                amend_sel = f'input[name="{amend_name}"]'
                logger.info(
                    "  Klicke Amend-Button: %s (row %d)", amend_sel, row_idx
                )
                await page.click(amend_sel)
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(2000)

                # Screenshot the amend form for discovery / debugging
                await self._screenshot(f"amend_form_{order_id}")

                # -------------------------------------------------------
                # Amend Form: Per-destination quantity fields
                # Each destination j has two fields:
                #   _idJsp126 = committed/bundle qty
                #   _idJsp140 = pieces qty (this is what we amend)
                # -------------------------------------------------------
                filled_any = False
                dest_count = amend.get("dest_count", 5)  # default 5 destinations
                for j in range(dest_count):
                    qty_sel = self.SEL_AMEND_QTY_PIECES_TPL.replace(
                        "{j}", str(j)
                    )
                    try:
                        qty_field = page.locator(qty_sel)
                        if await qty_field.is_visible(timeout=2000):
                            current = await qty_field.input_value()
                            await qty_field.fill(str(neu_menge))
                            logger.info(
                                "  Dest[%d] Menge: %s -> %d", j, current, neu_menge
                            )
                            filled_any = True
                    except Exception:
                        break  # no more destinations

                if not filled_any:
                    logger.warning("  Keine Mengen-Felder gefunden fuer %s", order_id)
                    await self._screenshot(f"amend_qty_notfound_{order_id}")

                if stop_before_save:
                    success_count += 1
                    logger.info(
                        "  stop_before_save=True - Formular NICHT gespeichert "
                        "fuer Order %s",
                        order_id,
                    )
                    # Stay on the form for manual inspection / discovery
                    continue

                # Click Save button (verified: mainForm:_idJsp155)
                try:
                    await page.click(self.SEL_AMEND_SAVE)
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(2000)
                    logger.info("  Amend gespeichert: %s", order_id)
                except Exception as save_err:
                    logger.error(
                        "  Save-Button Fehler: %s", save_err
                    )
                    await self._screenshot(f"amend_save_error_{order_id}")

                success_count += 1
                logger.info("  Amend OK: %s", order_id)

                # Re-extract table data: JSF may re-render after save,
                # shifting row indices
                table_orders = await self.get_result_table_data()

            except Exception as e:
                logger.error("  Amend FEHLER %s: %s", order_id, e)
                await self._screenshot(f"amend_error_{order_id}")

        if stop_before_save:
            logger.info(
                "Amendments: %d/%d Felder ausgefuellt (NICHT gespeichert)",
                success_count, len(amendments),
            )
        else:
            logger.info(
                "Amendments: %d/%d erfolgreich",
                success_count, len(amendments),
            )
        return success_count

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------

    # IDIS Export Spalten-Definitionen
    # Pre-Over: 19 Felder (headerless, ";"-getrennt, CSV, Fix Field Content Length)
    # Post-Over: 20 Felder (wie Pre + Feld 20: Committed Quantity for Size)
    IDIS_FIELDS_PRE = [
        "import_date",      # 0  (A) - Format: 5012026 = 5. Jan 2026
        "order_number",     # 1  (B) - z.B. 77275-973-83-915-174
        "aros_number",      # 2  (C) - z.B. NEWAROS oder 72964470
        "supplier",         # 3  (D) - z.B. 77275
        "class",            # 4  (E) - z.B. 973
        "code",             # 5  (F) - z.B. 83
        "serial",           # 6  (G) - z.B. 915
        "shipping",         # 7  (H) - z.B. 174
        "country",          # 8  (I) - NL, D, B, F, A, CH, E, SK, OL
        "committed_qty",    # 9  (J) - Bestaetigte Menge
        "ordered_qty",      # 10 (K) - Bestellte Menge
        "picking_method",   # 11 (L) - 1=PCS, 2=SUP, 3=PPP
        "order_number_2",   # 12 (M) - Wiederholung Ordernummer
        "country_2",        # 13 (N) - Wiederholung Land
        "size",             # 14 (O) - Groesse (9, 10, 38, 134, ...)
        "qty_for_size",     # 15 (P) - Menge pro Groesse (QUERSUMMEN-SPALTE!)
        "item_number",      # 16 (Q) - Artikelnummer
        "selling_price",    # 17 (R) - Verkaufspreis
        "order_type",       # 18 (S) - S=Store, D=Depot
    ]

    # Post-Over hat 1 Feld mehr: Committed Quantity (for Size)
    IDIS_FIELDS_POST = IDIS_FIELDS_PRE + [
        "committed_qty_for_size",  # 19 (T) - Bestaetigte Menge pro Groesse
    ]

    # Alias fuer Rueckwaertskompatibilitaet
    IDIS_FIELDS = IDIS_FIELDS_PRE

    PICKING_MAP = {"1": "PCS", "2": "SUP", "3": "PPP"}

    def _parse_csv(self, csv_path: str) -> list[dict]:
        """Parst eine IDIS-Export-CSV (headerless, 19 Felder, ";"-getrennt)."""
        rows = []

        for encoding in ["utf-8-sig", "utf-8", "latin-1"]:
            try:
                with open(csv_path, "r", encoding=encoding) as f:
                    # Prüfe ob erste Zeile ein Header ist
                    first_line = f.readline().strip()
                    f.seek(0)

                    has_header = any(
                        h in first_line.lower()
                        for h in ["order", "supplier", "import", "date"]
                    )

                    if has_header:
                        reader = csv.DictReader(f, delimiter=";")
                        for row in reader:
                            normalized = self._normalize_export_row_dict(row)
                            if normalized:
                                rows.append(normalized)
                    else:
                        reader = csv.reader(f, delimiter=";")
                        for fields in reader:
                            if not fields or len(fields) < 15:
                                continue
                            normalized = self._normalize_export_row_positional(fields)
                            if normalized:
                                rows.append(normalized)
                break
            except UnicodeDecodeError:
                continue

        logger.info("CSV geparst: %d Zeilen aus %s", len(rows), csv_path)
        return rows

    @classmethod
    def _normalize_export_row_positional(cls, fields: list) -> dict | None:
        """Normalisiert eine CSV-Zeile anhand der Feldposition (headerless).

        IDIS Export: 19 Felder (Pre-Over) oder 20 Felder (Post-Over).
        Separator: ";", keine Kopfzeile, Fix Field Content Length.
        Feld 20 (nur Post-Over): Committed Quantity (for Size).
        """
        if len(fields) < 15:
            return None

        def safe_str(idx):
            return str(fields[idx]).strip() if idx < len(fields) else ""

        def safe_int(idx):
            try:
                return int(float(safe_str(idx).replace(",", ".")))
            except (ValueError, TypeError):
                return 0

        supplier = safe_str(3)
        cls_code = safe_str(4)
        code = safe_str(5)
        serial = safe_str(6)

        # AROS-Key: Supplier-Class-Code-Serial
        aros_key = f"{supplier}-{cls_code}-{code}-{serial}"

        # Picking Method: 1=PCS, 2=SUP, 3=PPP
        picking_raw = safe_str(11)
        abrufart = cls.PICKING_MAP.get(picking_raw, "PCS")

        # Order Type: S=Store, D=Depot
        order_type = safe_str(18) if len(fields) > 18 else "S"
        picking = "Store" if order_type.upper() == "S" else "Depot"

        row = {
            "order_id": safe_str(1),
            "aros_key": aros_key,
            "aros_number": safe_str(2),
            "supplier": supplier,
            "class": cls_code,
            "code": code,
            "serial": serial,
            "country": safe_str(8).upper(),
            "committed_qty": safe_int(9),
            "ordered_qty": safe_int(10),
            "abrufart": abrufart,
            "picking_method": picking_raw,
            "size": safe_str(14),
            "quantity": safe_int(15),  # Col P = Menge pro Groesse
            "item_number": safe_str(16),
            "selling_price": safe_str(17),
            "picking": picking,
            "order_type": order_type.upper(),
        }

        # Feld 20 (Post-Over): Committed Quantity (for Size)
        if len(fields) >= 20:
            row["committed_qty_for_size"] = safe_int(19)

        return row

    @staticmethod
    def _normalize_export_row_dict(row: dict) -> dict | None:
        """Normalisiert eine CSV-Zeile mit Headers (Fallback)."""
        if not row:
            return None

        result = {}
        for key in ["Ordernummer", "Order", "OrderNr", "order_id", "Order Number"]:
            if key in row and row[key]:
                result["order_id"] = str(row[key]).strip()
                break

        for key in ["Aros", "AROS", "aros"]:
            if key in row and row[key]:
                result["aros_key"] = str(row[key]).strip()
                break

        for key in ["Land", "Country", "country"]:
            if key in row and row[key]:
                result["country"] = str(row[key]).strip().upper()
                break

        for key in ["Menge", "Quantity", "Qty", "qty_for_size"]:
            if key in row and row[key]:
                try:
                    result["quantity"] = int(float(str(row[key]).replace(",", ".")))
                except (ValueError, TypeError):
                    pass
                break

        for key in ["Größe", "Groesse", "Size", "size"]:
            if key in row and row[key]:
                result["size"] = str(row[key]).strip()
                break

        if "order_id" not in result and "aros_key" not in result:
            return None

        result.setdefault("abrufart", "PCS")
        result.setdefault("picking", "Store")
        return result

    async def _screenshot(self, name: str):
        """Erstellt Screenshot bei Fehler."""
        if not self.screenshot_on_error or not self._page:
            return
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = self.exports_dir / f"screenshot_{name}_{ts}.png"
            await self._page.screenshot(path=str(path))
            logger.info("Screenshot gespeichert: %s", path)
        except Exception as e:
            logger.debug("Screenshot fehlgeschlagen: %s", e)


# ------------------------------------------------------------------
# Standalone-Test (nur Syntax/Import-Check, braucht VPN für echten Test)
# ------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("idis_browser.py – Module-Check OK")
    print(f"  IDIS_USERNAME gesetzt: {'ja' if os.getenv('IDIS_USERNAME') else 'nein'}")
    print(f"  IDIS_PASSWORD gesetzt: {'ja' if os.getenv('IDIS_PASSWORD') else 'nein'}")
