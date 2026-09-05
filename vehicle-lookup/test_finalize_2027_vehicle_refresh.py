import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

spec = importlib.util.spec_from_file_location(
    "finalize_2027_vehicle_refresh",
    MODULE_DIR / "finalize_2027_vehicle_refresh.py",
)
finalize = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["finalize_2027_vehicle_refresh"] = finalize
spec.loader.exec_module(finalize)


def row(make, model, vehicle_class="sedan", pricing_group="Sedan"):
    return {
        "year": "2027",
        "make": make,
        "model": model,
        "vehicle_class": vehicle_class,
        "pricing_group": pricing_group,
        "classification_source": "nhtsa_vpic_2027_reviewed",
        "review_status": "ok",
        "is_commercial": "false",
    }


class Finalize2027VehicleRefreshTests(unittest.TestCase):
    def test_customer_facing_normalization_removes_oddity_and_suffixes(self):
        with tempfile.TemporaryDirectory() as directory:
            corrections = Path(directory)
            reviewed = finalize.review_snapshot([
                row("Ford", "'34"),
                row("Alfa Romeo", "Giulia (952)"),
                row("Nissan", "Ariya MPV", "suv", "SUV"),
                row("Nissan", "Kicks MPV", "suv", "SUV"),
                row("Toyota", "Prius Prime (PHEV)"),
                row("Toyota", "RAV4 Prime (PHEV)", "suv", "SUV"),
            ], corrections)

        by_make_model = {(item["make"], item["model"]) for item in reviewed}
        self.assertNotIn(("Ford", "'34"), by_make_model)
        self.assertIn(("Alfa Romeo", "Giulia"), by_make_model)
        self.assertIn(("Nissan", "Ariya"), by_make_model)
        self.assertIn(("Nissan", "Kicks"), by_make_model)
        self.assertIn(("Toyota", "Prius Prime"), by_make_model)
        self.assertIn(("Toyota", "RAV4 Prime"), by_make_model)

    def test_reviewed_class_manifest_is_applied_to_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            corrections = Path(directory)
            path = corrections / "bentley.csv"
            fields = [
                "make", "model", "vehicle_class", "pricing_group",
                "classification_source", "review_status", "is_commercial",
            ]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "make": "Bentley",
                    "model": "Continental",
                    "vehicle_class": "coupe",
                    "pricing_group": "Coupe",
                    "classification_source": "manual_review",
                    "review_status": "ok",
                    "is_commercial": "false",
                })
            reviewed = finalize.review_snapshot([
                row("Bentley", "Continental")
            ], corrections)

        self.assertEqual(reviewed[0]["vehicle_class"], "coupe")
        self.assertEqual(reviewed[0]["pricing_group"], "Coupe")
        self.assertEqual(reviewed[0]["classification_source"], "manual_review")


if __name__ == "__main__":
    unittest.main()
