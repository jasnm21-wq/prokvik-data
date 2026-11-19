import copy
import unittest

from build_library import build, read_json
from export_application import application_catalog


class ApplicationExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = build()
        cls.review = read_json("application-review.json")

    def test_app_export_only_contains_explicit_approvals(self):
        export = application_catalog(self.library, self.review)
        records = {(item["brand"], item["series"]): item for item in export["products"]}
        self.assertEqual(len(records), self.library["counts"]["series"])
        self.assertNotIn("measurements", records["Johnson Window Films", "Supreme IR"])
        self.assertNotIn("manufacturer_warranty", records["XPEL", "PRIME XR Plus"])
        self.assertEqual(records["3M", "Color Stable Series"]["measurements"][0]["generation"], "CS IR")
        self.assertEqual(export["methods"]["3m_liner"]["basis"], "film_with_liner")

    def test_changed_source_requires_review_again(self):
        changed = copy.deepcopy(self.library)
        changed["records"][0]["notes"] = "new information"
        with self.assertRaisesRegex(ValueError, "Source library changed"):
            application_catalog(changed, self.review)

    def test_inherited_or_disputed_values_cannot_be_approved(self):
        review = copy.deepcopy(self.review)
        review["measurements"].append({"brand":"Johnson Window Films","product_line":"Supreme IR",
                                      "source":"L32","method":"johnson","shades":["35"],
                                      "fields":["measured_vlt_pct"]})
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            application_catalog(self.library, review)
