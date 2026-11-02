"""Offline business-rule checks: no SDK, model, or Atlas needed."""
import os
import unittest
from unittest.mock import patch
from stockout_agent.stockout import calculate_risk, check_stockout, SAMPLE_INVENTORY


class StockoutTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"PHARMA_DATA_SOURCE": "sample"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_shortage(self):
        result = check_stockout("CHI", "DRG-01")
        self.assertEqual((result["available_units"], result["hours_supply"], result["risk_level"]), (45, 18, "at_risk"))

    def test_covered_and_exact_threshold(self):
        self.assertEqual(check_stockout("OAK", "DRG-01")["risk_level"], "covered")
        self.assertEqual(check_stockout("CHI", "DRG-01", .75)["risk_level"], "covered")

    def test_reservations_and_quarantine(self):
        result = calculate_risk({"on_hand": 100, "reserved": 20, "quarantined": 20, "daily_demand": 60}, 2)
        self.assertEqual(result["days_supply"], 1)

    def test_missing_is_unknown(self):
        self.assertEqual(check_stockout("CHI", "UNKNOWN")["status"], "not_found")

    def test_invalid_arguments(self):
        for threshold in [0, -1, float("nan"), float("inf"), True, 366]:
            self.assertEqual(check_stockout("CHI", "DRG-01", threshold)["code"], "INVALID_THRESHOLD")
        self.assertEqual(check_stockout({"$ne": None}, "DRG-01")["code"], "INVALID_ID")

    def test_invalid_inventory(self):
        for changes in [{"daily_demand": 0}, {"on_hand": -1}, {"reserved": 99}]:
            with self.assertRaises(ValueError):
                calculate_risk({**SAMPLE_INVENTORY[("CHI", "DRG-01")], **changes}, 2)

    def test_atlas_requires_explicit_uri(self):
        with patch.dict(os.environ, {"PHARMA_DATA_SOURCE": "atlas", "PHARMA_ATLAS_URI": ""}):
            self.assertEqual(check_stockout("CHI", "DRG-01")["code"], "MISSING_ATLAS_URI")


if __name__ == "__main__":
    unittest.main()
