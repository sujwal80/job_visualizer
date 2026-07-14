#!/usr/bin/env python3
"""
Test Suite: tests/test_database_state_tracking.py
Verifies state tracking fields (tagging_status, classification_status, last_crawled)
backfilling in DBManager.load_db(), merging in DBManager.merge_startup(),
and the logo extraction logic in LinkedInScraper.get_company_details().
Ensures all network/DNS requests are mocked.
"""

import unittest
import sys
import os
import json
from unittest.mock import patch, MagicMock

# Add project root to path
workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, workspace_root)

from data_acquisition.db_manager import DBManager
from data_acquisition.pipelines.crawling.job_scrapers.linkedin_scraper import LinkedInScraper

class TestDatabaseStateTracking(unittest.TestCase):
    def setUp(self):
        os.environ["DELAY_MULTIPLIER"] = "0.0"
        self.db_path = os.path.join(workspace_root, "tests", "test_temp_db.json")
        # Remove if exists
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass
        lock_path = self.db_path + ".lock"
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except OSError:
                pass

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass
        lock_path = self.db_path + ".lock"
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except OSError:
                pass

    def _write_db(self, data):
        with open(self.db_path, "w") as f:
            json.dump(data, f, indent=2)

    def _read_db(self):
        with open(self.db_path, "r") as f:
            return json.load(f)

    def test_load_db_backfilling(self):
        # 1. Test database loading with missing state tracking fields
        initial_data = [
            # A: Missing all tracking fields, has valid coords, has industry
            {
                "id": 1,
                "name": "Startup A",
                "lat": 12.95,
                "lng": 77.60,
                "location_tagged": None,
                "industry": "AI"
            },
            # B: Missing all tracking fields, has location_tagged=True, no industry
            {
                "id": 2,
                "name": "Startup B",
                "lat": None,
                "lng": None,
                "location_tagged": True,
                "industry": " "
            },
            # C: Missing all tracking fields, fallback coordinates, no industry
            {
                "id": 3,
                "name": "Startup C",
                "lat": 12.9716,
                "lng": 77.5946,
                "location_tagged": False,
                "industry": None
            }
        ]
        self._write_db(initial_data)
        
        manager = DBManager(db_path=self.db_path)
        startups = manager.get_all_startups()
        
        # Verify Startup A
        s_a = [s for s in startups if s["id"] == 1][0]
        self.assertEqual(s_a["tagging_status"], "completed")
        self.assertEqual(s_a["classification_status"], "completed")
        self.assertIsNone(s_a["last_crawled"])
        
        # Verify Startup B
        s_b = [s for s in startups if s["id"] == 2][0]
        self.assertEqual(s_b["tagging_status"], "completed")
        self.assertEqual(s_b["classification_status"], "pending")
        self.assertIsNone(s_b["last_crawled"])
        
        # Verify Startup C (fallback coordinates -> tagging_status is pending)
        s_c = [s for s in startups if s["id"] == 3][0]
        self.assertEqual(s_c["tagging_status"], "pending")
        self.assertEqual(s_c["classification_status"], "pending")
        self.assertIsNone(s_c["last_crawled"])

    @patch("data_acquisition.db_manager.validate_website_domain")
    @patch("data_acquisition.db_manager.check_job_active")
    @patch("data_acquisition.db_manager.validate_logo_image")
    @patch("data_acquisition.db_manager.DBManager.geocode_address")
    def test_merge_startup_preserves_or_updates_tracking_fields(self, mock_geocode, mock_validate_logo, mock_check_job, mock_validate_web):
        # Setup mocks
        mock_validate_web.side_effect = lambda url: (True, url, None)
        mock_check_job.return_value = (True, "Active")
        mock_validate_logo.return_value = True
        mock_geocode.return_value = (12.9352, 77.6245)

        # 1. Existing startup merge
        initial_data = [
            {
                "id": 1,
                "name": "Startup Merge",
                "website": "https://startup-merge.com",
                "logo_domain": "startup-merge.com",
                "tagging_status": "pending",
                "classification_status": "pending",
                "last_crawled": "2026-07-01T00:00:00Z"
            }
        ]
        self._write_db(initial_data)

        manager = DBManager(db_path=self.db_path)

        # Candidate company details with updated tracking status
        candidate = {
            "name": "Startup Merge",
            "website": "https://startup-merge.com",
            "industry": "Fintech",
            "tagging_status": "completed",
            "classification_status": "completed",
            "last_crawled": "2026-07-14T22:00:00Z"
        }

        merged = manager.merge_startup(candidate, [])
        self.assertIsNotNone(merged)
        self.assertEqual(merged["tagging_status"], "completed")
        self.assertEqual(merged["classification_status"], "completed")
        self.assertEqual(merged["last_crawled"], "2026-07-14T22:00:00Z")

        # Reload DB from file to verify save persisted the updates
        saved_data = self._read_db()
        s_saved = saved_data[0]
        self.assertEqual(s_saved["tagging_status"], "completed")
        self.assertEqual(s_saved["classification_status"], "completed")
        self.assertEqual(s_saved["last_crawled"], "2026-07-14T22:00:00Z")

    @patch("data_acquisition.db_manager.validate_website_domain")
    @patch("data_acquisition.db_manager.check_job_active")
    @patch("data_acquisition.db_manager.validate_logo_image")
    @patch("data_acquisition.db_manager.DBManager.geocode_address")
    def test_merge_new_startup_populates_tracking_fields(self, mock_geocode, mock_validate_logo, mock_check_job, mock_validate_web):
        # Setup mocks
        mock_validate_web.side_effect = lambda url: (True, url, None)
        mock_check_job.return_value = (True, "Active")
        mock_validate_logo.return_value = True
        mock_geocode.return_value = (12.9352, 77.6245)

        self._write_db([])
        manager = DBManager(db_path=self.db_path)

        candidate = {
            "name": "New Startup",
            "website": "https://new-startup.com",
            "industry": "Software",
            "tagging_status": "completed",
            "classification_status": "completed",
            "last_crawled": "2026-07-14T22:00:00Z"
        }

        merged = manager.merge_startup(candidate, [])
        self.assertIsNotNone(merged)
        self.assertEqual(merged["tagging_status"], "completed")
        self.assertEqual(merged["classification_status"], "completed")
        self.assertEqual(merged["last_crawled"], "2026-07-14T22:00:00Z")

        # Verify default fallback for fields when candidate doesn't supply them
        candidate_defaults = {
            "name": "Default Startup",
            "website": "https://default-startup.com",
            "industry": ""
        }
        merged_defaults = manager.merge_startup(candidate_defaults, [])
        self.assertIsNotNone(merged_defaults)
        # Default value fallback
        self.assertEqual(merged_defaults["tagging_status"], "pending")
        self.assertEqual(merged_defaults["classification_status"], "pending")
        self.assertIsNone(merged_defaults["last_crawled"])

    @patch("requests.get")
    def test_linkedin_scraper_logo_extraction(self, mock_get):
        company_slug = "test-company"
        
        html_with_logo_src = """
        <html>
            <body>
                <section class="top-card-layout">
                    <h1>Test Company</h1>
                    <img class="artdeco-entity-image" src="https://media.licdn.com/dms/image/C4D04AQE.png" />
                </section>
                <dl>
                    <dt>Website</dt>
                    <dd><a href="https://www.testcompany.com">testcompany.com</a></dd>
                    <dt>Industry</dt>
                    <dd>Software Development</dd>
                    <dt>Company size</dt>
                    <dd>11-50 employees</dd>
                </dl>
            </body>
        </html>
        """
        
        mock_response = MagicMock(status_code=200, text=html_with_logo_src, url=f"https://www.linkedin.com/company/{company_slug}")
        mock_get.return_value = mock_response
        
        scraper = LinkedInScraper()
        details = scraper.get_company_details(company_slug)
        
        self.assertIsNotNone(details)
        self.assertEqual(details["name"], "Test Company")
        self.assertEqual(details["logo_svg_url"], "https://media.licdn.com/dms/image/C4D04AQE.png")
        self.assertEqual(details["logo_domain"], "testcompany.com")
        self.assertEqual(details["industry"], "Software Development")
        
        # Test fallback data-delayed-url
        html_with_delayed_logo = """
        <html>
            <body>
                <section class="top-card-layout">
                    <h1>Test Delayed Company</h1>
                    <img class="artdeco-entity-image" data-delayed-url="https://media.licdn.com/dms/image/delayed.png" />
                </section>
                <dl>
                    <dt>Website</dt>
                    <dd>https://www.delayedcompany.com</dd>
                </dl>
            </body>
        </html>
        """
        mock_response_delayed = MagicMock(status_code=200, text=html_with_delayed_logo, url=f"https://www.linkedin.com/company/{company_slug}")
        mock_get.return_value = mock_response_delayed
        
        details_delayed = scraper.get_company_details(company_slug)
        self.assertIsNotNone(details_delayed)
        self.assertEqual(details_delayed["logo_svg_url"], "https://media.licdn.com/dms/image/delayed.png")
        self.assertEqual(details_delayed["logo_domain"], "delayedcompany.com")

if __name__ == "__main__":
    unittest.main()
