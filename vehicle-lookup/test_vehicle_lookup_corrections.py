import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, MODULE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


apply_module = load_module(
    "vehicle_lookup_corrections",
    "apply_vehicle_lookup_corrections.py",
)
validate_module = load_module(
    "vehicle_lookup_correction_validation",
    "validate_vehicle_lookup_corrections.py",
)


class VehicleLookupCorrectionTests(unittest.TestCase):
    def test_real_catalog_is_fully_finalized_for_reviewed_corrections(self):
        lookup = MODULE_DIR / "vehicle_lookup_import_ready.csv"
        corrections_dir = MODULE_DIR / "corrections"
        with lookup.open(newline="", encoding="utf-8") as handle:
            expected_rows = sum(1 for _ in csv.DictReader(handle))
        expected_keys = len(apply_module.load_corrections(corrections_dir))

        result = validate_module.regenerate_and_validate(lookup, corrections_dir)

        self.assertEqual(result["total_rows"], expected_rows)
        self.assertEqual(result["correction_keys"], expected_keys)
        self.assertEqual(result["changed_rows"], 0)
        self.assertEqual(result["already_correct_keys"], expected_keys)

    def test_correction_is_idempotent_and_preserves_unlisted_qx_model(self):
        fieldnames = [
            "year", "make", "model", "vehicle_class", "pricing_group",
            "classification_source", "review_status", "is_commercial",
        ]
        rows = [
            {
                "year": "2021", "make": "Infiniti", "model": "Q50",
                "vehicle_class": "suv", "pricing_group": "SUV",
                "classification_source": "rules_model", "review_status": "ok",
                "is_commercial": "false",
            },
            {
                "year": "2021", "make": "Infiniti", "model": "Q60",
                "vehicle_class": "suv", "pricing_group": "SUV",
                "classification_source": "rules_model", "review_status": "ok",
                "is_commercial": "false",
            },
            {
                "year": "2021", "make": "Infiniti", "model": "QX60",
                "vehicle_class": "suv", "pricing_group": "SUV",
                "classification_source": "rules_model", "review_status": "ok",
                "is_commercial": "false",
            },
        ]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lookup = root / "lookup.csv"
            corrections_dir = root / "corrections"
            output = root / "output.csv"
            corrections_dir.mkdir()
            with lookup.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            with (corrections_dir / "reviewed.csv").open(
                "w", newline="", encoding="utf-8"
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames[1:])
                writer.writeheader()
                writer.writerows([
                    {
                        "make": "Infiniti", "model": "Q50",
                        "vehicle_class": "sedan", "pricing_group": "Sedan",
                        "classification_source": "manual", "review_status": "ok",
                        "is_commercial": "false",
                    },
                    {
                        "make": "Infiniti", "model": "Q60",
                        "vehicle_class": "coupe", "pricing_group": "Coupe",
                        "classification_source": "manual", "review_status": "ok",
                        "is_commercial": "false",
                    },
                ])

            first = apply_module.apply_corrections(lookup, corrections_dir, output)
            self.assertEqual(first["changed_rows"], 2)
            with output.open(newline="", encoding="utf-8") as handle:
                by_model = {row["model"]: row for row in csv.DictReader(handle)}
            self.assertEqual(by_model["Q50"]["vehicle_class"], "sedan")
            self.assertEqual(by_model["Q60"]["vehicle_class"], "coupe")
            self.assertEqual(by_model["QX60"]["vehicle_class"], "suv")

            second = root / "second.csv"
            second_result = apply_module.apply_corrections(
                output, corrections_dir, second
            )
            self.assertEqual(second_result["changed_rows"], 0)

    def test_write_replaces_catalog_atomically(self):
        fieldnames = [
            "year", "make", "model", "vehicle_class", "pricing_group",
            "classification_source", "review_status", "is_commercial",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lookup = root / "lookup.csv"
            corrections_dir = root / "corrections"
            corrections_dir.mkdir()
            with lookup.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow({
                    "year": "2021", "make": "Infiniti", "model": "Q50",
                    "vehicle_class": "suv", "pricing_group": "SUV",
                    "classification_source": "rules_model", "review_status": "ok",
                    "is_commercial": "false",
                })
            with (corrections_dir / "reviewed.csv").open(
                "w", newline="", encoding="utf-8"
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames[1:])
                writer.writeheader()
                writer.writerow({
                    "make": "Infiniti", "model": "Q50",
                    "vehicle_class": "sedan", "pricing_group": "Sedan",
                    "classification_source": "manual", "review_status": "ok",
                    "is_commercial": "false",
                })

            result = validate_module.regenerate_and_validate(
                lookup, corrections_dir, write=True
            )
            self.assertEqual(result["changed_rows"], 1)
            with lookup.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["vehicle_class"], "sedan")
            self.assertEqual(list(root.glob(".lookup.csv.*.tmp")), [])

    def test_validator_rejects_identity_or_unreviewed_changes(self):
        fieldnames = [
            "year", "make", "model", "vehicle_class", "pricing_group",
            "classification_source", "review_status", "is_commercial",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = root / "before.csv"
            after = root / "after.csv"
            corrections_dir = root / "corrections"
            corrections_dir.mkdir()
            row = {
                "year": "2021", "make": "Toyota", "model": "Camry",
                "vehicle_class": "sedan", "pricing_group": "Sedan",
                "classification_source": "rules_model", "review_status": "ok",
                "is_commercial": "false",
            }
            changed = {**row, "vehicle_class": "suv", "pricing_group": "SUV"}
            for path, payload in ((before, row), (after, changed)):
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerow(payload)
            with (corrections_dir / "reviewed.csv").open(
                "w", newline="", encoding="utf-8"
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames[1:])
                writer.writeheader()
                writer.writerow({
                    "make": "Toyota", "model": "Corolla",
                    "vehicle_class": "sedan", "pricing_group": "Sedan",
                    "classification_source": "manual", "review_status": "ok",
                    "is_commercial": "false",
                })

            with self.assertRaises(ValueError):
                validate_module.validate_delta(before, after, corrections_dir)


if __name__ == "__main__":
    unittest.main()
