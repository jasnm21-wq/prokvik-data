import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

spec = importlib.util.spec_from_file_location(
    "vehicle_model_year_refresh",
    MODULE_DIR / "refresh_vehicle_model_year.py",
)
refresh = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["vehicle_model_year_refresh"] = refresh
spec.loader.exec_module(refresh)


class VehicleModelYearRefreshTests(unittest.TestCase):
    def test_nhtsa_make_match_is_exact_not_partial(self):
        self.assertTrue(refresh.nhtsa_make_matches("Ford", "FORD"))
        self.assertFalse(refresh.nhtsa_make_matches("Ford", "STANFORD CUSTOMS"))
        self.assertFalse(refresh.nhtsa_make_matches("Mini", "MINI BIG TRUCKS"))
        self.assertFalse(refresh.nhtsa_make_matches("Kia", "MGS GRAND SPORT (MARDIKIAN)"))
        self.assertFalse(refresh.nhtsa_make_matches("Land Rover", "LAND ROVER SANTANA"))

    def test_commercial_rows_are_excluded(self):
        for make, model in (
            ("Chevrolet", "BrightDrop"),
            ("Ford", "F-550"),
            ("Ford", "F-600"),
            ("Hyundai", "Xcient"),
            ("Tesla", "Semi"),
            ("Volvo", "VHD"),
        ):
            with self.subTest(make=make, model=model):
                self.assertFalse(refresh.is_customer_facing_model(make, model))

    def test_shop_relevant_trucks_and_vans_remain_allowed(self):
        for make, model in (
            ("Ford", "F-150"),
            ("Ford", "F-250"),
            ("Chevrolet", "Silverado"),
            ("Ram", "1500"),
            ("Toyota", "Tacoma"),
            ("Ford", "Transit"),
            ("Mercedes-Benz", "Sprinter"),
            ("Ram", "ProMaster 1500"),
            ("Chevrolet", "Express"),
            ("GMC", "Savana"),
        ):
            with self.subTest(make=make, model=model):
                self.assertTrue(refresh.is_customer_facing_model(make, model))

    def test_reviewed_class_clarifications(self):
        cases = (
            ("Mustang Mach-E", "Passenger Car", ("suv", "SUV")),
            ("GV80", "Passenger Car", ("suv", "SUV")),
            ("Hummer EV Pickup", "Passenger Car", ("truck", "Truck")),
            ("Prelude", "Passenger Car", ("coupe", "Coupe")),
            ("Prologue", "Passenger Car", ("suv", "SUV")),
            ("Ioniq 5", "Passenger Car", ("suv", "SUV")),
            ("QX80", "Passenger Car", ("suv", "SUV")),
            ("Nissan Z", "Passenger Car", ("coupe", "Coupe")),
            ("Corolla Cross", "Passenger Car", ("suv", "SUV")),
            ("Jetta", "Passenger Car", ("sedan", "Sedan")),
            ("Odyssey", "Multipurpose Passenger Vehicle (MPV)", ("van", "Van")),
            ("Ridgeline", "Truck", ("truck", "Truck")),
        )
        for model, vehicle_type, expected in cases:
            with self.subTest(model=model):
                self.assertEqual(
                    refresh.classify_customer_vehicle(model, vehicle_type),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
