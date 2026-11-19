import csv
from pathlib import Path
import tempfile
import unittest

from build_library import build, check_value, export, normalized_shade, check_reported_percentage


class SpecificationLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = build()

    def record(self, brand, series, shade, source, method):
        return next(r for r in self.library["records"] if
                    (r["brand"], r["product_line"], r["nominal_shade"], r["source"], r["method"])
                    == (brand, series, shade, source, method))

    def test_local_and_official_provenance(self):
        sources = self.library["sources"]
        self.assertEqual(len(self.library["research"]), len(self.library["brands"]))
        self.assertEqual(len({s["sha256"] for s in sources.values() if s["kind"] == "local"}),
                         self.library["counts"]["local_documents"])
        self.assertEqual(sources["L03"]["brand"], "SolarFX")
        self.assertEqual(sources["L57"]["paths"], ["llumar-automotive-window-film-performance-data.pdf"])
        self.assertTrue(sources["W-nexfil-chart"]["sha256"])
        self.assertEqual(sources["W-coolvu-arch"]["scope"], "architectural")
        self.assertFalse(any(sources[r["source"]].get("scope") == "architectural" for r in self.library["records"]))

    def test_strict_units_values_and_missing(self):
        self.assertEqual(check_value("uv_rejection", "≥ 99.0%"), "≥99.0")
        self.assertEqual(check_value("uv_rejection", "99%+"), "99+")
        self.assertEqual(normalized_shade("05:Bronze"), "5:Bronze")
        self.assertEqual(check_value("tser_pct", "0"), "0")
        check_reported_percentage("up to 72")
        for field, value in [("tser_pct", "101"), ("measured_vlt_pct", "-1"),
                             ("shgc", "1.02"), ("ply_count", "1.5"), ("shading_coefficient", "0.59%")]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_value(field, value)
        missing = self.record("Madico", "Black Pearl Nano-Ceramic", "10", "L34", "madico")
        self.assertNotIn("shading_coefficient", missing["measurements"])
        self.assertIn(".0.45", missing["notes"])

    def test_substrate_and_ir_metrics_are_not_interchanged(self):
        green = self.record("3M", "Ceramic IR", "35", "L01", "3m_auto75")
        clear = self.record("3M", "Ceramic IR", "35", "L01", "3m_clear89")
        liner = self.record("3M", "Ceramic IR", "35", "L01", "3m_liner")
        self.assertEqual(green["measurements"]["measured_vlt_pct"], "37")
        self.assertEqual(clear["measurements"]["measured_vlt_pct"], "45")
        self.assertEqual(liner["measurements"], {"irr_pct": "85"})
        a = self.record("Solar Gard", "XenithIR", "35", "W-solargard-xenith", "solar_clear")
        b = self.record("Solar Gard", "XenithIR", "35", "W-solargard-xenith", "solar_film")
        self.assertEqual(a["measurements"]["irer_pct"], "65")
        self.assertEqual(b["measurements"], {"sirr_pct": "93"})
        self.assertEqual(self.library["methods"][b["method"]]["basis"], "film_only")

    def test_reconciled_eastman_row_and_qualifier(self):
        row = self.record("LLumar", "ATR", "40", "L57", "eastman_clear6")
        self.assertEqual(row["measurements"]["glare_reduction_pct"], "48")
        notes = self.record("LLumar", "IRX", "15", "L57", "eastman_clear6")["notes"]
        self.assertIn("development", notes)

    def test_offered_shade_is_not_a_measured_vlt(self):
        nexfil = next(f for f in self.library["facts"] if f["product_line"] == "LUX IR80")
        self.assertIn("35", nexfil["available_shades"])
        series = self.record("Nexfil", "LUX IR80", None, "W-nexfil-automotive", "unknown")
        self.assertNotIn("measured_vlt_pct", series["measurements"])

    def test_conflicting_readings_and_published_balance_are_preserved(self):
        conflict = next(x for x in self.library["discrepancies"] if
                        (x["brand"], x["product_line"], x["shade"], x["metric"]) ==
                        ("Johnson Window Films", "Supreme IR", "35", "measured_vlt_pct"))
        self.assertEqual(conflict["kind"], "conflicting_same_method")
        self.assertEqual({a["value"] for a in conflict["alternatives"]}, {"32", "33"})
        warning = next(w for w in self.library["validation_warnings"] if
                       w["product_line"] == "CENTURION IR30" and w["shade"] == "42")
        self.assertEqual(warning["total"], "124.0")

    def test_warranty_scope_leaves_contested_terms_visible(self):
        w = next(w for w in self.library["warranties"] if w["source"] == "W-xpel-warranty")
        self.assertEqual(w["evidence"], "conflicting_terms")
        self.assertIn("Conflicting", w["transfer"])
        self.assertNotIn("Carbon X", next(w for w in self.library["warranties"]
                                         if w["source"] == "W-kavaca-2022")["products"])

    def test_repeatable_exports_cover_every_catalog_entry(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            export(self.library, Path(a))
            export(build(), Path(b))
            for path in Path(a).iterdir():
                self.assertEqual(path.read_bytes(), (Path(b) / path.name).read_bytes(), path.name)
            with (Path(a) / "product-coverage.csv").open(encoding="utf-8", newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), len(self.library["products"]))
            with (Path(a) / "manufacturer-coverage.csv").open(encoding="utf-8", newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), len(self.library["brands"]))
            self.assertNotIn("__LIBRARY__", (Path(a) / "review.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
