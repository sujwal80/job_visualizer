#!/usr/bin/env python3
"""
Unit Verification Suite for RevalidationHealingEngine
Path: tests/test_revalidation_healing_engine.py

Verifies all 5 Acceptance Criteria:
- AC1: Foreign Regional TLD Healing
- AC2: Same-City Deduplication & Merging
- AC3: Cross-City Record Preservation (Zero-Regression Guardrail)
- AC4: Street Address Zero-Regression Guardrail
- AC5: Coordinate Bounding Box Verification
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.revalidate_healing_engine import RevalidationHealingEngine, CITY_BOUNDS


class TestRevalidationHealingEngine(unittest.TestCase):
    def setUp(self):
        self.engine = RevalidationHealingEngine(db_path="/tmp/test_revalidate_healing_db.json")

    def test_ac1_foreign_regional_tld_healing(self):
        """
        AC1: Verify foreign regional TLDs (.it, .de, .fr, .es, .au, .br) are healed to canonical .com
        without modifying valid existing .com/.in/.tech domains.
        """
        records = [
            {"id": 1, "name": "ItalianCorp", "website": "https://www.italiancorp.it", "logo_domain": "italiancorp.it"},
            {"id": 2, "name": "GermanCorp", "website": "https://www.germancorp.de/about", "logo_domain": "germancorp.de"},
            {"id": 3, "name": "FrenchCorp", "website": "https://www.frenchcorp.fr", "logo_domain": "frenchcorp.fr"},
            {"id": 4, "name": "ValidCorp", "website": "https://www.validcorp.in", "logo_domain": "validcorp.in"},
            {"id": 5, "name": "ComCorp", "website": "https://www.comcorp.com", "logo_domain": "comcorp.com"},
        ]

        healed_count = self.engine.heal_foreign_tlds(records)
        self.assertEqual(healed_count, 3)
        self.assertEqual(records[0]["website"], "https://www.italiancorp.com")
        self.assertEqual(records[0]["logo_domain"], "italiancorp.com")
        self.assertEqual(records[1]["website"], "https://www.germancorp.com/about")
        self.assertEqual(records[1]["logo_domain"], "germancorp.com")
        self.assertEqual(records[2]["website"], "https://www.frenchcorp.com")
        self.assertEqual(records[2]["logo_domain"], "frenchcorp.com")

        # Ensure valid domains untouched
        self.assertEqual(records[3]["website"], "https://www.validcorp.in")
        self.assertEqual(records[4]["website"], "https://www.comcorp.com")

    def test_ac2_same_city_deduplication_and_merging(self):
        """
        AC2: Verify same-city duplicate records are merged into the canonical lowest-ID record,
        consolidating unique job openings and inheriting richer metadata.
        """
        records = [
            {
                "id": 10,
                "name": "Jar Tech",
                "city": "Bengaluru",
                "website": "",
                "description": "",
                "head_count": 50,
                "job_openings": [{"title": "Frontend Eng", "url": "https://job/1"}]
            },
            {
                "id": 5,
                "name": "Jar Tech Pvt Ltd",
                "city": "Bengaluru, Karnataka",
                "website": "https://myjar.app",
                "description": "Daily savings app",
                "head_count": 100,
                "job_openings": [{"title": "Backend Eng", "url": "https://job/2"}]
            },
            {
                "id": 20,
                "name": "Jar Tech Private Limited",
                "city": "Bengaluru",
                "website": "",
                "description": "",
                "head_count": 75,
                "job_openings": [
                    {"title": "Backend Eng", "url": "https://job/2"},  # duplicate job
                    {"title": "DevOps Eng", "url": "https://job/3"}
                ]
            }
        ]

        merged_count = self.engine.deduplicate_city_records(records)
        self.assertEqual(merged_count, 2)
        self.assertEqual(len(records), 1)

        canonical = records[0]
        self.assertEqual(canonical["id"], 5)
        self.assertEqual(canonical["website"], "https://myjar.app")
        self.assertEqual(canonical["description"], "Daily savings app")
        self.assertEqual(canonical["head_count"], 100)

        job_urls = {j["url"] for j in canonical["job_openings"]}
        self.assertEqual(job_urls, {"https://job/1", "https://job/2", "https://job/3"})

    def test_ac3_cross_city_record_preservation(self):
        """
        AC3: Verify zero-regression guardrail where records of the same company name
        across DIFFERENT metro cities are preserved independently and never merged.
        """
        records = [
            {"id": 1, "name": "Microsoft", "city": "Bengaluru", "job_openings": []},
            {"id": 2, "name": "Microsoft", "city": "Hyderabad", "job_openings": []},
            {"id": 3, "name": "Microsoft", "city": "Delhi NCR", "job_openings": []},
        ]

        merged_count = self.engine.deduplicate_city_records(records)
        self.assertEqual(merged_count, 0)
        self.assertEqual(len(records), 3)
        ids = {s["id"] for s in records}
        self.assertEqual(ids, {1, 2, 3})

    def test_ac4_street_address_zero_regression_guardrail(self):
        """
        AC4: Verify verified OpenStreetMap street addresses are protected and never
        overwritten by generic city names or default labels.
        """
        records = [
            {
                "id": 1,
                "name": "DetailedCorp",
                "city": "Bengaluru",
                "office_address": "3rd Floor, Tower B, Ecospace, Bellandur, Bengaluru, Karnataka 560103"
            },
            {
                "id": 2,
                "name": "GenericCorp",
                "city": "Bengaluru",
                "office_address": "Bengaluru, Karnataka"
            }
        ]

        preserved = self.engine.verify_address_guardrails(records)
        self.assertEqual(preserved, 1)
        self.assertTrue(records[0].get("_address_verified_guardrail"))
        self.assertFalse(records[1].get("_address_verified_guardrail", False))

    def test_ac5_coordinate_bounding_box_verification(self):
        """
        AC5: Verify coordinates lie within CITY_BOUNDS[metro] and out-of-bounds coordinates
        are healed to the metro city's default center.
        """
        records = [
            {"id": 1, "name": "ValidBLR", "city": "Bengaluru", "lat": 12.9716, "lng": 77.5946},
            {"id": 2, "name": "OutBLR", "city": "Bengaluru", "lat": 0.0, "lng": 0.0},
            {"id": 3, "name": "OutHYD", "city": "Hyderabad", "lat": 45.0, "lng": -120.0},
        ]

        fixed_count = self.engine.verify_and_heal_coordinates(records)
        self.assertEqual(fixed_count, 2)

        # Record 1 untouched
        self.assertEqual(records[0]["lat"], 12.9716)
        self.assertEqual(records[0]["lng"], 77.5946)

        # Record 2 healed to Bengaluru default
        self.assertEqual(records[1]["lat"], CITY_BOUNDS["Bengaluru"]["default"][0])
        self.assertEqual(records[1]["lng"], CITY_BOUNDS["Bengaluru"]["default"][1])

        # Record 3 healed to Hyderabad default
        self.assertEqual(records[2]["lat"], CITY_BOUNDS["Hyderabad"]["default"][0])
        self.assertEqual(records[2]["lng"], CITY_BOUNDS["Hyderabad"]["default"][1])


if __name__ == "__main__":
    unittest.main()
