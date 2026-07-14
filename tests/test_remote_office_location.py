"""
Comprehensive Automated Test Suite for Dynamic Remote Office Classification & Idempotency Tagging (`R1`-`R4`)

Tests:
1. Haversine distance accuracy across international and domestic coordinate pairs (`haversine_distance_km`).
2. Multi-city dynamic classification (`check_remote_office_status`) across targets and threshold env overrides.
3. `LocationEnricher.enrich()` idempotency short-circuiting (`location_tagged: True`).
4. Batch verification script (`verify_location_tags.py`) processing, tagging, remote classification, and idempotency short-circuiting (`updated == 0`).
5. Floating-point safety (`NaN`/`Infinity`) handling and compliant JSON sanitization.
"""

import json
import math
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Add project root and data_acquisition to path
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.geo_config import (
    MULTI_CITY_CENTERS,
    get_city_center_coordinates,
    DEFAULT_TARGET_CITY,
)
from data_acquisition.pipelines.tagging.remote_office_classifier import (
    haversine_distance_km,
    check_remote_office_status,
)
from data_acquisition.pipelines.tagging.location_enricher import LocationEnricher
from data_acquisition.pipelines.tagging.verify_location_tags import verify_location_tags


class TestRemoteOfficeLocation(unittest.TestCase):
    def setUp(self):
        self.original_threshold = os.environ.get("REMOTE_OFFICE_DISTANCE_THRESHOLD_KM")

    def tearDown(self):
        if self.original_threshold is not None:
            os.environ["REMOTE_OFFICE_DISTANCE_THRESHOLD_KM"] = self.original_threshold
        else:
            os.environ.pop("REMOTE_OFFICE_DISTANCE_THRESHOLD_KM", None)

    def test_01_haversine_distance_accuracy_international_and_domestic(self):
        """
        Prove Haversine distance calculations are accurate across international
        (SF <-> NY, London <-> Paris) and domestic (Bangalore <-> Electronic City, Delhi <-> Gurgaon) pairs.
        """
        # International: SF (37.7749, -122.4194) <-> NY (40.7128, -74.0060) ~ 4129 km
        dist_sf_ny = haversine_distance_km(37.7749, -122.4194, 40.7128, -74.0060)
        self.assertIsNotNone(dist_sf_ny)
        self.assertTrue(4100.0 < dist_sf_ny < 4160.0, f"Expected ~4129 km for SF<->NY, got {dist_sf_ny}")

        # International: London (51.5074, -0.1278) <-> Paris (48.8566, 2.3522) ~ 343 km
        dist_london_paris = haversine_distance_km(51.5074, -0.1278, 48.8566, 2.3522)
        self.assertIsNotNone(dist_london_paris)
        self.assertTrue(335.0 < dist_london_paris < 355.0, f"Expected ~343 km for London<->Paris, got {dist_london_paris}")

        # Domestic India: Bangalore Center (12.9716, 77.5946) <-> Electronic City (12.8452, 77.6602) ~ 15.6 km
        dist_blr_ecity = haversine_distance_km(12.9716, 77.5946, 12.8452, 77.6602)
        self.assertIsNotNone(dist_blr_ecity)
        self.assertTrue(14.0 < dist_blr_ecity < 18.0, f"Expected ~15.6 km for BLR<->ECity, got {dist_blr_ecity}")

        # Domestic India: Delhi Center (28.6139, 77.2090) <-> Gurgaon Center (28.4595, 77.0266) ~ 24.5 km
        dist_del_ggn = haversine_distance_km(28.6139, 77.2090, 28.4595, 77.0266)
        self.assertIsNotNone(dist_del_ggn)
        self.assertTrue(22.0 < dist_del_ggn < 27.0, f"Expected ~24.5 km for Delhi<->Gurgaon, got {dist_del_ggn}")

        # Identical point should be 0.0
        dist_zero = haversine_distance_km(12.9716, 77.5946, 12.9716, 77.5946)
        self.assertAlmostEqual(dist_zero, 0.0, places=5)

    def test_02_check_remote_office_status_multi_city_dynamic(self):
        """
        Prove check_remote_office_status dynamically works for multiple target cities
        and respects dynamic threshold environment overrides.
        """
        # Coordinate in Pune: (18.5204, 73.8567)
        record = {
            "name": "Pune Cloud Systems",
            "lat": 18.5204,
            "lng": 73.8567,
            "city": "Pune"
        }

        # 1. Target city = "Bengaluru" (distance ~732 km > 50 km) -> classified as remote
        check_remote_office_status(record, target_city="Bengaluru")
        self.assertTrue(record.get("is_remote_office"), "Expected Pune office to be classified as remote from Bengaluru")
        self.assertTrue(record.get("remote_office_distance_km") > 50.0)
        self.assertIn(" (Remote Office)", record.get("city"))

        # 2. Target city = "Pune" (distance 0 km <= 50 km) -> classified as local
        check_remote_office_status(record, target_city="Pune")
        self.assertFalse(record.get("is_remote_office"), "Expected Pune office to be classified as local in Pune")
        self.assertEqual(record.get("remote_office_distance_km"), 0.0)
        self.assertNotIn(" (Remote Office)", record.get("city"))

        # 3. Dynamic Threshold environment override
        os.environ["REMOTE_OFFICE_DISTANCE_THRESHOLD_KM"] = "1000.0"
        record_delhi = {
            "name": "Delhi Tech",
            "lat": 28.6139,
            "lng": 77.2090,
            "city": "Delhi"
        }
        # Distance Delhi <-> Bengaluru ~ 1740 km > 1000 km threshold -> True
        check_remote_office_status(record_delhi, target_city="Bengaluru")
        self.assertTrue(record_delhi.get("is_remote_office"))

        # Now set threshold higher than 2000 km -> False
        os.environ["REMOTE_OFFICE_DISTANCE_THRESHOLD_KM"] = "2500.0"
        check_remote_office_status(record_delhi, target_city="Bengaluru")
        self.assertFalse(record_delhi.get("is_remote_office"))

    def test_03_location_enricher_idempotency_short_circuiting(self):
        """
        Prove LocationEnricher.enrich() sets location_tagged: True and short-circuits
        immediately (returns False, 0 API calls) on subsequent invocations.
        """
        mock_db = MagicMock()
        # geocode_address returns exact coordinates
        mock_db.geocode_address.return_value = (12.9780, 77.6400)

        enricher = LocationEnricher(mock_db)

        record = {
            "name": "Indiranagar AI",
            "office_address": "100 Feet Road, Indiranagar, Bangalore",
            "lat": None,
            "lng": None
        }

        # First enrichment call: should perform geocoding and set location_tagged = True
        result_1 = enricher.enrich(record, target_city="Bengaluru")
        self.assertTrue(result_1)
        self.assertEqual(record["lat"], 12.9780)
        self.assertEqual(record["lng"], 77.6400)
        self.assertTrue(record.get("location_tagged"))
        self.assertFalse(record.get("is_remote_office"))
        self.assertEqual(mock_db.geocode_address.call_count, 1)

        # Second enrichment call on the exact same record: must short-circuit (0 API calls)
        result_2 = enricher.enrich(record, target_city="Bengaluru")
        self.assertFalse(result_2, "Expected short-circuit on location_tagged=True")
        self.assertEqual(mock_db.geocode_address.call_count, 1, "Must make 0 additional API calls")

    def test_04_batch_verification_script_and_idempotency(self):
        """
        Prove batch verification script (verify_location_tags.py) processes records,
        marks location_tagged: True, classifies remote offices, and processes 0 new
        records (updated_count == 0) on subsequent idempotent runs.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_db_path = os.path.join(tmp_dir, "test_startups.json")
            initial_records = [
                {
                    "id": 1,
                    "name": "Local Bangalore Startup",
                    "lat": 12.9716,
                    "lng": 77.5946,
                    "city": "Bengaluru"
                },
                {
                    "id": 2,
                    "name": "Remote Pune Office",
                    "lat": 18.5204,
                    "lng": 73.8567,
                    "city": "Pune"
                },
                {
                    "id": 3,
                    "name": "Already Tagged Startup",
                    "lat": 12.9716,
                    "lng": 77.5946,
                    "city": "Bengaluru",
                    "location_tagged": True
                }
            ]
            with open(tmp_db_path, "w") as f:
                json.dump(initial_records, f, indent=2)

            # First run: should process records 1 and 2, and skip record 3
            stats_run1 = verify_location_tags(db_path=tmp_db_path, target_city="Bengaluru", idempotent=True)
            self.assertEqual(stats_run1["total"], 3)
            self.assertEqual(stats_run1["updated"], 2)
            self.assertEqual(stats_run1["skipped"], 1)
            self.assertEqual(stats_run1["remote_count"], 1)

            # Check saved database contents
            with open(tmp_db_path, "r") as f:
                saved = json.load(f)
            self.assertTrue(all(r.get("location_tagged") is True for r in saved))
            self.assertFalse(saved[0]["is_remote_office"])
            self.assertTrue(saved[1]["is_remote_office"])
            self.assertIn(" (Remote Office)", saved[1]["city"])

            # Second run: with idempotency enabled, should update 0 records
            stats_run2 = verify_location_tags(db_path=tmp_db_path, target_city="Bengaluru", idempotent=True)
            self.assertEqual(stats_run2["total"], 3)
            self.assertEqual(stats_run2["updated"], 0, "Idempotent re-run must process 0 records")
            self.assertEqual(stats_run2["skipped"], 3)
            self.assertEqual(stats_run2["remote_count"], 1)

    def test_05_floating_point_safety_nan_infinity(self):
        """
        Prove floating-point safety: NaN and Infinity inputs are handled cleanly
        without crashing or writing non-compliant JSON literals.
        """
        # 1. haversine_distance_km with NaN/Infinity should return None
        self.assertIsNone(haversine_distance_km(float("nan"), 77.5, 12.9, 77.5))
        self.assertIsNone(haversine_distance_km(12.9, float("inf"), 12.9, 77.5))
        self.assertIsNone(haversine_distance_km(12.9, 77.5, float("-inf"), 77.5))
        self.assertIsNone(haversine_distance_km(None, 77.5, 12.9, 77.5))

        # 2. check_remote_office_status with NaN / Infinity attributes
        record_corrupt = {
            "name": "Corrupt Coords Corp",
            "lat": float("nan"),
            "lng": float("inf"),
            "city": "Bengaluru"
        }
        check_remote_office_status(record_corrupt, target_city="Bengaluru")
        self.assertIsNone(record_corrupt.get("lat"))
        self.assertIsNone(record_corrupt.get("lng"))
        self.assertIsNone(record_corrupt.get("remote_office_distance_km"))
        self.assertFalse(record_corrupt.get("is_remote_office"))

        # 3. Verify batch script cleans NaN/Inf before writing compliant JSON
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_db_path = os.path.join(tmp_dir, "corrupt_db.json")
            records = [
                {
                    "id": 1,
                    "name": "Invalid Float Startup 1",
                    "lat": float("nan"),
                    "lng": 77.5946,
                    "city": "Bengaluru"
                },
                {
                    "id": 2,
                    "name": "Invalid Float Startup 2",
                    "lat": 12.9716,
                    "lng": float("inf"),
                    "city": "Bengaluru"
                }
            ]
            # Write out initial records (mocking raw dict in memory before file write)
            with open(tmp_db_path, "w") as f:
                json.dump([
                    {"id": 1, "name": "Invalid Float Startup 1", "lat": None, "lng": 77.5946, "city": "Bengaluru"},
                    {"id": 2, "name": "Invalid Float Startup 2", "lat": 12.9716, "lng": None, "city": "Bengaluru"}
                ], f)

            stats = verify_location_tags(db_path=tmp_db_path, target_city="Bengaluru", idempotent=True)
            self.assertEqual(stats["updated"], 2)

            # Load saved file and verify JSON compliance
            with open(tmp_db_path, "r") as f:
                content = f.read()
            self.assertNotIn(": NaN", content)
            self.assertNotIn(": Infinity", content)
            saved = json.loads(content)
            self.assertTrue(all(r.get("location_tagged") is True for r in saved))


if __name__ == "__main__":
    unittest.main()
