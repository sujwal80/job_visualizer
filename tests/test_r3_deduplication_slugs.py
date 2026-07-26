#!/usr/bin/env python3
"""
Unit tests for Requirement R3: Company Name Deduplication & Job Slug Validation.
Verifies:
1. Normalization strips corporate legal suffixes (Pvt Ltd, Inc, LLC, etc.) and incubator tags ((YC W21), YC S20)
   while retaining descriptive business words (Technologies, Solutions, Services, Labs, Software, Systems).
2. DBManager.find_startup matches variants like 'Jar', 'Jar Pvt Ltd', and 'Jar Technologies' to canonical record 'Jar'.
3. Job slug mismatch rejection prevents attaching cross-company jobs (e.g. flipkart job attached to Namma Cart,
   or bairesdev job attached to another startup).
4. Aggregator names (LinkedIn, Naukri, Glassdoor, Indeed, Wellfound, Cutshort, Instahyre, Hirist, Y Combinator, YCombinator)
   are rejected as startup company names.
"""

import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)

from data_acquisition.db_manager import DBManager

class TestR3DeduplicationSlugs(unittest.TestCase):
    def setUp(self):
        os.environ["DELAY_MULTIPLIER"] = "0.0"
        self.db_path = os.path.join(workspace_root, "tests", "test_r3_temp_db.json")
        self._cleanup_db()

    def tearDown(self):
        self._cleanup_db()

    def _cleanup_db(self):
        for path in [self.db_path, self.db_path + ".lock", self.db_path + ".tmp"]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _write_db(self, data):
        with open(self.db_path, "w") as f:
            json.dump(data, f, indent=2)

    # -------------------------------------------------------------------------
    # 1. Text Normalization Tests
    # -------------------------------------------------------------------------
    def test_normalize_text_legal_suffixes_and_yc_tags(self):
        db = DBManager(db_path=self.db_path)

        # Basic stripping of legal suffixes
        self.assertEqual(db._normalize_text("Jar Pvt Ltd"), "jar")
        self.assertEqual(db._normalize_text("Jar Private Limited"), "jar")
        self.assertEqual(db._normalize_text("Jar Inc"), "jar")
        self.assertEqual(db._normalize_text("Jar Inc."), "jar")
        self.assertEqual(db._normalize_text("Jar LLC"), "jar")
        self.assertEqual(db._normalize_text("Jar Ltd"), "jar")
        self.assertEqual(db._normalize_text("Jar Corp"), "jar")
        self.assertEqual(db._normalize_text("Jar Corporation"), "jar")
        self.assertEqual(db._normalize_text("Jar Pte Ltd"), "jar")
        self.assertEqual(db._normalize_text("Jar Pte. Ltd."), "jar")
        self.assertEqual(db._normalize_text("Jar Co."), "jar")
        self.assertEqual(db._normalize_text("Jar Company"), "jar")

        # Stripping YC / incubator tags
        self.assertEqual(db._normalize_text("Jar (YC W21)"), "jar")
        self.assertEqual(db._normalize_text("Jar (YC S20)"), "jar")
        self.assertEqual(db._normalize_text("Jar (YC ...)"), "jar")
        self.assertEqual(db._normalize_text("Jar YC W21"), "jar")
        self.assertEqual(db._normalize_text("Jar (YC W21) Pvt Ltd"), "jar")

        # Retaining descriptive business words
        self.assertEqual(db._normalize_text("Jar Technologies"), "jartechnologies")
        self.assertEqual(db._normalize_text("Jar Solutions"), "jarsolutions")
        self.assertEqual(db._normalize_text("Jar Services"), "jarservices")
        self.assertEqual(db._normalize_text("Jar Labs"), "jarlabs")
        self.assertEqual(db._normalize_text("Jar Software"), "jarsoftware")
        self.assertEqual(db._normalize_text("Jar Systems"), "jarsystems")

    # -------------------------------------------------------------------------
    # 2. Startup Matching (find_startup) Tests
    # -------------------------------------------------------------------------
    def test_find_startup_canonical_matching(self):
        # Database containing canonical company 'Jar'
        initial_db = [
            {
                "id": 1,
                "name": "Jar",
                "city": "Bengaluru",
                "website": "https://myjar.app",
                "logo_domain": "myjar.app",
                "job_openings": []
            }
        ]
        self._write_db(initial_db)
        db = DBManager(db_path=self.db_path)

        # Match exact canonical name
        match_jar = db.find_startup("Jar", "")
        self.assertIsNotNone(match_jar)
        self.assertEqual(match_jar["id"], 1)

        # Match legal suffix variant
        match_pvt = db.find_startup("Jar Pvt Ltd", "")
        self.assertIsNotNone(match_pvt)
        self.assertEqual(match_pvt["id"], 1)

        # Match descriptive word variant
        match_tech = db.find_startup("Jar Technologies", "")
        self.assertIsNotNone(match_tech)
        self.assertEqual(match_tech["id"], 1)

        # Match YC tag variant
        match_yc = db.find_startup("Jar (YC W21)", "")
        self.assertIsNotNone(match_yc)
        self.assertEqual(match_yc["id"], 1)

    # -------------------------------------------------------------------------
    # 3. Job Slug Mismatch Rejection Tests
    # -------------------------------------------------------------------------
    @patch("data_acquisition.db_manager.check_job_active")
    def test_job_slug_mismatch_rejection(self, mock_check_job):
        mock_check_job.return_value = (True, "Active")

        initial_db = [
            {
                "id": 1,
                "name": "Namma Cart",
                "city": "Bengaluru",
                "website": "https://nammacart.com",
                "logo_domain": "nammacart.com",
                "job_openings": []
            },
            {
                "id": 2,
                "name": "Acme Startup",
                "city": "Bengaluru",
                "website": "https://acmestartup.com",
                "logo_domain": "acmestartup.com",
                "job_openings": []
            }
        ]
        self._write_db(initial_db)
        db = DBManager(db_path=self.db_path)

        namma_cart = db.find_startup("Namma Cart", "")
        self.assertIsNotNone(namma_cart)

        # Job explicitly mentioning flipkart attached to Namma Cart
        cross_job_flipkart = {
            "title": "Software Engineer",
            "url": "https://www.naukri.com/job-listings-software-engineer-at-flipkart-bangalore-4417583838",
            "company_name": "Flipkart"
        }

        # Job mentioning bairesdev attached to Acme Startup
        cross_job_bairesdev = {
            "title": "Senior Frontend Developer",
            "url": "https://in.linkedin.com/jobs/bairesdev-jobs-software-engineer-12345",
            "company_name": "BairesDev"
        }

        # Valid job for Namma Cart
        valid_job_namma = {
            "title": "Backend Lead",
            "url": "https://www.naukri.com/job-listings-backend-lead-at-namma-cart-bangalore-12345",
            "company_name": "Namma Cart"
        }

        # Merge jobs into Namma Cart
        db._merge_job_openings(namma_cart, [cross_job_flipkart, valid_job_namma])

        # Verify only valid job was merged, flipkart job rejected
        openings = namma_cart.get("job_openings", [])
        self.assertEqual(len(openings), 1)
        self.assertEqual(openings[0]["title"], "Backend Lead")

        # Merge bairesdev job into Acme Startup
        acme = db.find_startup("Acme Startup", "")
        db._merge_job_openings(acme, [cross_job_bairesdev])
        self.assertEqual(len(acme.get("job_openings", [])), 0)

    # -------------------------------------------------------------------------
    # 4. Aggregator Name Rejection Tests
    # -------------------------------------------------------------------------
    @patch("data_acquisition.db_manager.validate_website_domain")
    @patch("data_acquisition.db_manager.check_job_active")
    @patch("data_acquisition.db_manager.validate_logo_image")
    @patch("data_acquisition.db_manager.DBManager.geocode_address")
    def test_aggregator_name_rejection(self, mock_geocode, mock_validate_logo, mock_check_job, mock_validate_web):
        mock_validate_web.side_effect = lambda url: (True, url, None)
        mock_check_job.return_value = (True, "Active")
        mock_validate_logo.return_value = True
        mock_geocode.return_value = (12.9716, 77.5946)

        self._write_db([])
        db = DBManager(db_path=self.db_path)

        aggregator_names = [
            "LinkedIn", "Naukri", "Glassdoor", "Indeed", "Wellfound",
            "Cutshort", "Instahyre", "Hirist", "Y Combinator", "YCombinator"
        ]

        # Verify is_aggregator_name returns True for all listed aggregators
        for agg in aggregator_names:
            self.assertTrue(db.is_aggregator_name(agg), f"Failed to identify aggregator: {agg}")

        # Verify merge_startup rejects aggregator names
        for agg in aggregator_names:
            result = db.merge_startup({"name": agg, "website": f"https://{agg.lower().replace(' ', '')}.com"}, [])
            self.assertIsNone(result, f"Failed to reject merge_startup for aggregator: {agg}")

        # Verify find_startup returns None for aggregator names
        for agg in aggregator_names:
            self.assertIsNone(db.find_startup(agg, ""))

        # Verify database remains empty (no aggregators registered as startups)
        self.assertEqual(len(db.get_all_startups()), 0)

if __name__ == "__main__":
    unittest.main()
