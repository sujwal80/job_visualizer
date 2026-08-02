#!/usr/bin/env python3
"""
Unit tests for Request Deduplication, Caching, and Algorithmic Normalization
Path: tests/test_request_deduplication_cache.py
"""

import json
import os
import shutil
import unittest
from data_acquisition.db_manager import DBManager

class TestRequestDeduplicationCache(unittest.TestCase):
    def setUp(self):
        self.test_dir = "/tmp/test_dedup_cache"
        os.makedirs(self.test_dir, exist_ok=True)
        self.db_path = os.path.join(self.test_dir, "startups.json")
        sample_data = [
            {
                "id": 1,
                "name": "Accenture in India",
                "city": "Bengaluru",
                "website": "https://www.accenture.com",
                "logo_domain": "accenture.com",
                "logo_svg_url": "https://logo.url/acc.svg",
                "industry": "Software Development"
            },
            {
                "id": 2,
                "name": "Google",
                "city": "Bengaluru",
                "website": "https://www.google.com",
                "logo_domain": "google.com",
                "logo_svg_url": "https://logo.url/goo.svg",
                "industry": "Software Development"
            }
        ]
        with open(self.db_path, "w") as f:
            json.dump(sample_data, f)
        self.db = DBManager(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_geocode_cache_hit(self):
        # Insert artificial entry into geocode cache
        test_query = "test company, mumbai"
        self.db.geocode_cache[test_query] = [19.076, 72.877]
        lat, lng = self.db._geocode_osm(test_query)
        self.assertAlmostEqual(lat, 19.076)
        self.assertAlmostEqual(lng, 72.877)

    def test_algorithmic_normalization(self):
        # Test that legal suffixes and descriptive words are stripped algorithmically without hardcoding
        n1 = self.db._normalize_base_text("Accenture in India")
        n2 = self.db._normalize_base_text("Accenture Private Limited")
        n3 = self.db._normalize_base_text("Accenture Technologies")
        self.assertEqual(n1, "accenture")
        self.assertEqual(n2, "accenture")
        self.assertEqual(n3, "accenture")

    def test_find_startup_any_city(self):
        # Test finding Accenture across another city to inherit core metadata
        found = self.db.find_startup_any_city("Accenture")
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], 1)
        self.assertEqual(found["website"], "https://www.accenture.com")

    def test_duplicate_prevention(self):
        # Ensure that searching for Accenture in India or Accenture returns existing record
        found = self.db.find_startup("Accenture", logo_domain="accenture.com", target_city="Bengaluru")
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], 1)

if __name__ == "__main__":
    unittest.main()
