#!/usr/bin/env python3
"""
Unit and Adversarial Verification Suite for Revalidate Hourly Service
Path: tests/test_revalidate_hourly_service.py

Tests:
1. run_service_once(db_path, public_db_path) execution and atomic synchronization
2. Byte-for-byte dataset identity between backend and public databases
3. CLI argument handling (--run-once, --daemon, --db, --public-db, --interval)
4. Integration with adversarial test cases (TLD in query param, PIN generic addresses, boundary coords)
5. Daemon loop iteration and graceful stop handling
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.revalidate_hourly_service import run_service_once, run_daemon_loop, main
from data_acquisition.revalidate_healing_engine import CITY_BOUNDS


class TestRevalidateHourlyService(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_startups.json")
        self.public_db_path = os.path.join(self.test_dir, "test_public_startups.json")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_1_run_service_once_success_and_sync(self):
        """
        Verify run_service_once executes healing and synchronizes backend/startups.json
        with public/static/data/startups.json byte-for-byte.
        """
        records = [
            {
                "id": 1,
                "name": "HourlyTest Startup",
                "city": "Bengaluru",
                "website": "https://www.hourlytest.it",
                "logo_domain": "hourlytest.it",
                "lat": 12.9716,
                "lng": 77.5946,
                "office_address": "Plot 14, Sector 3, HSR Layout, Bengaluru"
            }
        ]
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)

        metrics = run_service_once(db_path=self.db_path, public_db_path=self.public_db_path)

        self.assertEqual(metrics["foreign_tlds_healed"], 1)
        self.assertTrue(os.path.exists(self.public_db_path))

        with open(self.db_path, "rb") as f1, open(self.public_db_path, "rb") as f2:
            self.assertEqual(
                f1.read(),
                f2.read(),
                "Backend DB and public static DB must be byte-for-byte identical after run_service_once!"
            )

        # Verify no temporary sync files are left behind
        self.assertFalse(os.path.exists(self.public_db_path + ".tmp_sync"))
        self.assertFalse(os.path.exists(self.db_path + ".tmp_heal"))

    def test_2_run_service_once_adversarial_integration(self):
        """
        Verify run_service_once correctly handles adversarial test cases from audit_report:
        - TLD in query string (.it in query param should not be mutated)
        - Generic PIN address should not be marked as verified street address
        - Exact bounding box boundary coordinates should be preserved
        """
        blr_bounds = CITY_BOUNDS["Bengaluru"]
        min_lat, max_lat = blr_bounds["lat"]
        min_lng, max_lng = blr_bounds["lng"]

        records = [
            {
                "id": 10,
                "name": "QueryAdv",
                "city": "Bengaluru",
                "website": "https://example.in/search?country=de&lang=it",
                "logo_domain": "example.in",
                "office_address": "Bengaluru 560001, India",
                "lat": min_lat,
                "lng": min_lng
            },
            {
                "id": 20,
                "name": "QueryAdv Pvt Ltd",
                "city": "Bengaluru",
                "website": "https://example.in/search?country=de&lang=it",
                "logo_domain": "example.in",
                "office_address": "Plot 14, Sector 3, HSR Layout, Bengaluru",
                "lat": max_lat,
                "lng": max_lng
            }
        ]
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)

        metrics = run_service_once(db_path=self.db_path, public_db_path=self.public_db_path)

        self.assertEqual(metrics["duplicates_merged"], 1)
        self.assertEqual(metrics["out_of_bounds_fixed"], 0)

        with open(self.db_path, "r", encoding="utf-8") as f:
            saved = json.load(f)

        self.assertEqual(len(saved), 1)
        # Verify query param .it was NOT mutated
        self.assertEqual(saved[0]["website"], "https://example.in/search?country=de&lang=it")
        # Verify canonical inherited real street address over generic PIN address
        self.assertEqual(saved[0]["office_address"], "Plot 14, Sector 3, HSR Layout, Bengaluru")

    def test_3_cli_main_run_once(self):
        """
        Verify CLI main() invocation with --run-once flag executes single pass.
        """
        records = [
            {"id": 1, "name": "CliTest", "city": "Bengaluru", "website": "https://clitest.de"}
        ]
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)

        test_args = ["revalidate_hourly_service.py", "--run-once", "--db", self.db_path, "--public-db", self.public_db_path]
        with patch.object(sys, "argv", test_args):
            main()

        with open(self.db_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved[0]["website"], "https://clitest.com")

    def test_4_daemon_loop_graceful_stop(self):
        """
        Verify daemon loop executes at least once and handles SystemExit gracefully.
        """
        records = [
            {"id": 1, "name": "DaemonTest", "city": "Bengaluru", "website": "https://daemontest.in"}
        ]
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)

        with patch("time.sleep", side_effect=SystemExit):
            run_daemon_loop(db_path=self.db_path, public_db_path=self.public_db_path, interval_seconds=1)

        self.assertTrue(os.path.exists(self.public_db_path))

    def test_5_missing_db_file(self):
        """
        Verify run_service_once raises FileNotFoundError when database path does not exist.
        """
        non_existent_db = os.path.join(self.test_dir, "missing_db.json")
        with self.assertRaises(FileNotFoundError):
            run_service_once(db_path=non_existent_db, public_db_path=self.public_db_path)


if __name__ == "__main__":
    unittest.main()
