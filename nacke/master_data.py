"""
master_data.py – Masterdatei Orders + Over Matrix laden & indexieren.

Liest:
  - Masterdatei Orders.xlsx (Sheet "Alle Orders" + "OL Kartonage")
  - Over Matrix.xlsx

Stellt Lookup-Funktionen bereit:
  - get_order_info(aros_key) → Abrufart, Picking, Bundle Size Store/Depot
  - get_ol_bundle(aros_key) → OL-Kartongröße
  - validate_orders(export_rows) → (valid_rows, missing_keys)
"""

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class MasterData:
    """Zentrale Klasse für Masterdaten-Zugriff."""

    def __init__(self, config_path: str = "config.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)

        self._orders: dict = {}       # AROS-Key → Row-Dict
        self._ol_kartonage: dict = {}  # AROS-Key → Bundle Size
        self._over_matrix: pd.DataFrame = pd.DataFrame()

        self._load_masterdatei()
        self._load_over_matrix()

    # ------------------------------------------------------------------
    # Laden
    # ------------------------------------------------------------------

    def _load_masterdatei(self):
        """Masterdatei Orders.xlsx laden und indexieren.

        Bekannte Spalten (Sheet "Alle Orders"):
          A: Verketten Raussuchliste (Key: z.B. "84854-100-00-510")
          B: (doppelt)
          C: Datum
          D: Supplier
          E: Class
          F: Code
          G: Serial
          H: Abrufart CSA (PCS, PPP, SUP)
          I: Picking (PCS, PPP, PPPwPCS, SUP)
          J: Einstellung Bundle Size 3er Kartonage (Store)
          K: Einstellung RPR Kartonage (Depot)
          L: Artikel
          M: Besonderheiten/Meldung an C&A
          N: Lagerort

        Bekannte Spalten (Sheet "OL Kartonage"):
          A-D: Supplier, Class, Code, Serial
          E: Picking
          F: kleiner OL Karton
          G: grosser OL Karton
          H: Verkettung (Key)
          I: Liste Karton (effektiver Wert)
          J: Bemerkung
        """
        path = Path(self.cfg["paths"]["masterdatei"])
        if not path.exists():
            logger.warning("Masterdatei nicht gefunden: %s – Bundle-Daten leer.", path)
            return

        sheet_orders = self.cfg["masterdatei_sheets"]["alle_orders"]
        sheet_ol = self.cfg["masterdatei_sheets"]["ol_kartonage"]

        # --- Sheet "Alle Orders" ---
        df_orders = pd.read_excel(path, sheet_name=sheet_orders)
        logger.info("Masterdatei '%s': %d Zeilen geladen", sheet_orders, len(df_orders))

        cols = list(df_orders.columns)
        logger.debug("Spalten Alle Orders: %s", cols)

        # Index per "Verketten Raussuchliste" (Col A) – das ist der AROS-Key
        for _, row in df_orders.iterrows():
            key = self._build_aros_key(row)
            if key:
                self._orders[key] = row.to_dict()

        logger.info("Alle Orders indexiert: %d Einträge", len(self._orders))

        # --- Sheet "OL Kartonage" ---
        try:
            df_ol = pd.read_excel(path, sheet_name=sheet_ol)
            logger.info("Sheet '%s': %d Zeilen", sheet_ol, len(df_ol))
            for _, row in df_ol.iterrows():
                key = self._build_ol_key(row)
                if key:
                    self._ol_kartonage[key] = row.to_dict()
        except ValueError:
            logger.warning("Sheet '%s' nicht gefunden – OL-Daten leer.", sheet_ol)

    def _load_over_matrix(self):
        """Over Matrix.xlsx laden."""
        path = Path(self.cfg["paths"]["over_matrix"])
        if not path.exists():
            logger.warning("Over Matrix nicht gefunden: %s", path)
            return

        self._over_matrix = pd.read_excel(path)
        logger.info("Over Matrix geladen: %d Zeilen", len(self._over_matrix))

    # ------------------------------------------------------------------
    # Key-Builder
    # ------------------------------------------------------------------

    @staticmethod
    def _is_nan(val) -> bool:
        """Prüft ob ein Wert NaN/leer ist (pandas-kompatibel)."""
        if val is None:
            return True
        try:
            import pandas as pd
            if pd.isna(val):
                return True
        except (TypeError, ValueError):
            pass
        s = str(val).strip().lower()
        return s in ("", "nan", "none", "---")

    @staticmethod
    def _build_composite_key(row, col_names: list[str]) -> str | None:
        """Baut einen zusammengesetzten Key aus Supplier-Class-Code-Serial."""
        if not all(c in row.index for c in col_names):
            return None
        parts = []
        for c in col_names:
            v = str(row[c]).strip()
            try:
                v = str(int(float(v)))
            except (ValueError, TypeError):
                pass
            parts.append(v)
        if all(p and p.lower() not in ("nan", "none", "") for p in parts):
            return "-".join(parts)
        return None

    @classmethod
    def _build_aros_key(cls, row) -> str | None:
        """Baut den AROS-Key aus einer Zeile (Sheet "Alle Orders").

        Priorität:
        1. "Verketten Raussuchliste" (Col A) – z.B. "84854-100-00-510"
        2. Supplier-Class-Code-Serial zusammenbauen
        """
        for col_name in [
            "Verketten Raussuchliste", "Verketten",
            "AROS", "Aros", "aros",
        ]:
            if col_name in row.index and not cls._is_nan(row[col_name]):
                val = str(row[col_name]).strip()
                if val and val != "---":
                    return val

        return cls._build_composite_key(row, ["Supplier", "Class", "Code", "Serial"])

    @classmethod
    def _build_ol_key(cls, row) -> str | None:
        """Baut den Key für OL Kartonage Sheet.

        Priorität:
        1. "Verkettung" (Col H)
        2. Supplier-Class-Code-Serial (Col A-D)
        """
        for col_name in ["Verkettung", "Verketten"]:
            if col_name in row.index and not cls._is_nan(row[col_name]):
                return str(row[col_name]).strip()

        return cls._build_composite_key(row, ["Supplier", "Class", "Code", "Serial"])

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_order_info(self, aros_key: str) -> dict | None:
        """Liefert Order-Infos für einen AROS-Key.

        Returns dict mit:
          - abrufart: str ("PCS", "PPP", "SUP")
          - picking: str ("PCS", "PPP", "PPPwPCS", "SUP")
          - bundle_size_store: float (Col J)
          - bundle_size_depot: float (Col K)
          - artikel: str
          - lagerort: str
          - besonderheiten: str
        oder None wenn Key nicht gefunden.
        """
        row = self._orders.get(aros_key)
        if row is None:
            return None

        # Abrufart CSA (Col H)
        abrufart = None
        for c in ["Abrufart CSA", "Abrufart", "abrufart"]:
            if c in row:
                val = str(row[c]).strip()
                if val and val != "nan":
                    abrufart = val
                    break

        # Picking (Col I)
        picking = None
        for c in ["Picking", "picking"]:
            if c in row:
                val = str(row[c]).strip()
                if val and val != "nan":
                    picking = val
                    break

        # Bundle Size Store (Col J) – explizite Spaltennamen
        BUNDLE_STORE_COLS = [
            "Einstellung Bundle Size 3 er Kartonage (Store)",
            "Einstellung Bundle Size 3er Kartonage (Store)",
            "Bundle Size Store",
            "Bundle Store",
        ]
        bundle_store = 0.0
        for c in BUNDLE_STORE_COLS:
            if c in row and self._safe_float(row[c]) > 0:
                bundle_store = self._safe_float(row[c])
                break

        # Bundle Size Depot (Col K) – explizite Spaltennamen
        BUNDLE_DEPOT_COLS = [
            "Einstellung RPR Kartonage (Depot)",
            "RPR Kartonage Depot",
            "Bundle Size Depot",
            "Bundle Depot",
        ]
        bundle_depot = 0.0
        for c in BUNDLE_DEPOT_COLS:
            if c in row and self._safe_float(row[c]) > 0:
                bundle_depot = self._safe_float(row[c])
                break

        # Fallback: positional (Col J=index 9, K=index 10)
        cols = list(row.keys())
        if bundle_store == 0.0:
            bundle_store = self._safe_numeric(row, cols, 9)
        if bundle_depot == 0.0:
            bundle_depot = self._safe_numeric(row, cols, 10)

        # Zusatzinfos
        artikel = self._safe_str(row, "Artikel")
        lagerort = self._safe_str(row, "Lagerort")
        besonderheiten = self._safe_str(row, "Besonderheiten/Meldung an C&A")

        return {
            "abrufart": abrufart or "PCS",
            "picking": picking or "PCS",
            "bundle_size_store": bundle_store,
            "bundle_size_depot": bundle_depot,
            "artikel": artikel,
            "lagerort": lagerort,
            "besonderheiten": besonderheiten,
            "raw": row,
        }

    def get_ol_bundle(self, aros_key: str) -> float | None:
        """OL-Kartonage Bundle Size für einen AROS-Key.

        OL Kartonage Sheet Spalten:
          F: kleiner OL Karton
          G: grosser OL Karton
          I: Liste Karton (effektiver Wert = F oder G)
        """
        row = self._ol_kartonage.get(aros_key)
        if row is None:
            return None

        # Priorität 1: "Liste Karton" (Col I) – der effektive Wert
        for c in ["Liste Karton", "Liste_Karton"]:
            if c in row:
                val = self._safe_float(row[c])
                if val > 0:
                    return val

        # Priorität 2: kleiner/grosser OL Karton
        for c in row:
            cl = str(c).lower()
            if "karton" in cl and ("klein" in cl or "gross" in cl or "liste" in cl):
                val = self._safe_float(row[c])
                if val > 0:
                    return val

        # Fallback: Col I (index 8)
        cols = list(row.keys())
        if len(cols) > 8:
            val = self._safe_float(row.get(cols[8]))
            if val > 0:
                return val

        return None

    def get_over_matrix(self) -> pd.DataFrame:
        """Gibt die Over Matrix als DataFrame zurück."""
        return self._over_matrix

    def should_overconfirm(self, country: str, abrufart: str) -> bool:
        """Prüft in der Over Matrix ob für Land+Abrufart hochgesetzt werden soll.

        Over Matrix Format (tatsächlich):
          Col A: Land (NL, D, B, F, E, A, SK, CH, OL)
          Col B: "1" (=PCS) → "Ja"/"Nein"
          Col C: "3" (=PPP) → "Ja"/"Nein"
          Col E: Legende (PCS=1, PPP=3)

        REGEL: D (Deutschland) wird NIEMALS hochgesetzt.
        """
        never_countries = self.cfg.get("overconfirmation", {}).get(
            "never_hochsetzen_countries", ["D"]
        )
        if country.upper() in [c.upper() for c in never_countries]:
            return False

        if self._over_matrix.empty:
            return False

        df = self._over_matrix
        cols = list(df.columns)

        # Col A = Land (erster Spalte)
        land_col = cols[0]

        # Zeile für das Land finden
        mask = df[land_col].astype(str).str.strip().str.upper() == country.upper()
        matching = df[mask]

        if matching.empty:
            return False

        # Bestimme die richtige Spalte: PCS → Col B (Index 1), PPP → Col C (Index 2)
        abrufart_upper = abrufart.upper()
        if abrufart_upper == "PCS" and len(cols) > 1:
            col_idx = 1  # Col B = "1" (PCS)
        elif abrufart_upper == "PPP" and len(cols) > 2:
            col_idx = 2  # Col C = "3" (PPP)
        else:
            return False

        value_col = cols[col_idx]
        value = str(matching.iloc[0][value_col]).strip().lower()

        return value == "ja"

    # ------------------------------------------------------------------
    # Validierung
    # ------------------------------------------------------------------

    def validate_orders(self, aros_keys: list[str]) -> tuple[list[str], list[str]]:
        """Prüft welche AROS-Keys in der Masterdatei vorhanden sind.

        Returns: (valid_keys, missing_keys)
        """
        valid = []
        missing = []
        for key in aros_keys:
            if key in self._orders:
                valid.append(key)
            else:
                missing.append(key)

        if missing:
            logger.warning(
                "Fehlende Masterdaten für %d Orders: %s",
                len(missing),
                ", ".join(missing[:10]),
            )

        return valid, missing

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_numeric(row: dict, cols: list, col_idx: int) -> float:
        """Liest einen numerischen Wert aus Spalte per Index."""
        if col_idx < len(cols):
            val = row.get(cols[col_idx])
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        return 0.0

    @staticmethod
    def _safe_float(val) -> float:
        """Konvertiert einen Wert zu float, gibt 0.0 bei Fehler."""
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _safe_str(row: dict, col_name: str) -> str:
        """Liest einen String-Wert aus einer Spalte (case-insensitiv)."""
        col_lower = col_name.strip().lower()
        for c in row:
            if str(c).strip().lower() == col_lower:
                val = str(row[c]).strip()
                return "" if val.lower() in ("nan", "none") else val
        return ""


# ------------------------------------------------------------------
# Standalone-Test
# ------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    md = MasterData()
    print(f"Orders geladen: {len(md._orders)}")
    print(f"OL Kartonage: {len(md._ol_kartonage)}")
    print(f"Over Matrix: {len(md._over_matrix)} Zeilen")

    # Zeige erste 5 Keys
    for i, key in enumerate(list(md._orders.keys())[:5]):
        info = md.get_order_info(key)
        print(f"  {key}: Abrufart={info['abrufart']}, "
              f"Bundle Store={info['bundle_size_store']}, "
              f"Bundle Depot={info['bundle_size_depot']}")
