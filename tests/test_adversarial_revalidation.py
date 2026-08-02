#!/usr/bin/env python3
"""
Adversarial Stress-Test Verification Suite for RevalidationHealingEngine & Guardrails
Path: tests/test_adversarial_revalidation.py

This empirical test suite challenges:
1. TLD Healing Edge Cases (.com.br double extensions, domains with ports, unhealed logo_svg_url)
2. City-Scoped Deduplication Edge Cases (dropping jobs without URLs, dropping jobs sharing career portal URLs, generic address overwrites)
3. Street Address Guardrail Edge Cases (valid addresses formatted without commas)
4. Coordinate Bounding Box Edge Cases (unhandled NCR/Mumbai metro cities like Thane, Faridabad, Secunderabad)
"""

import json
import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.revalidate_healing_engine import RevalidationHealingEngine, CITY_BOUNDS
from data_acquisition.deduplicate_startups import get_metro_city


class TestAdversarialRevalidationEngine(unittest.TestCase):
    def setUp(self):
        self.engine = RevalidationHealingEngine(db_path="/tmp/test_adversarial_revalidate.json")

    def test_adv_1_tld_healing_double_extensions(self):
        """
        Challenge 1a: .com.br and .com.au domains.
        Current implementation replaces .br/.au with .com -> example.com.com (BUG).
        """
        records = [
            {"id": 1, "name": "BrazilTech", "website": "https://braziltech.com.br", "logo_domain": "braziltech.com.br"},
            {"id": 2, "name": "AussieTech", "website": "https://aussietech.com.au/about", "logo_domain": "aussietech.com.au"}
        ]
        self.engine.heal_foreign_tlds(records)
        # Verify if .com.br was wrongly converted to .com.com
        print("\n[Challenge 1a Result] website:", records[0]["website"])
        # We assert what a correct engine SHOULD produce, or document empirical failure:
        # A robust engine should produce https://braziltech.com or https://braziltech.in
        self.assertNotEqual(records[0]["website"], "https://braziltech.com.com",
                            "VULNERABILITY DETECTED: .com.br healed to .com.com!")
        self.assertNotEqual(records[1]["website"], "https://aussietech.com.com/about",
                            "VULNERABILITY DETECTED: .com.au healed to .com.com!")

    def test_adv_2_tld_healing_with_ports(self):
        """
        Challenge 1b: Foreign TLD URLs containing port numbers (e.g. :8080 or :443).
        Current regex pattern r'\\.(it|de|fr|es|au|br)(?=[/?#]|$)' misses TLD followed by a colon.
        """
        records = [
            {"id": 1, "name": "ItalianPort", "website": "http://italianport.it:8080/login", "logo_domain": "italianport.it"}
        ]
        healed = self.engine.heal_foreign_tlds(records)
        print("\n[Challenge 1b Result] website:", records[0]["website"], "Healed count:", healed)
        self.assertEqual(records[0]["website"], "http://italianport.com:8080/login",
                         "VULNERABILITY DETECTED: .it domain with port :8080 remained unhealed!")

    def test_adv_3_dedup_dropping_jobs_without_url(self):
        """
        Challenge 2a: Deduplication silently drops unique job openings that have no url/job_url key.
        """
        records = [
            {"id": 10, "name": "Jar Tech", "city": "Bengaluru", "job_openings": [{"title": "Frontend Eng", "url": "https://job/1"}]},
            {"id": 20, "name": "Jar Tech Pvt Ltd", "city": "Bengaluru", "job_openings": [{"title": "Senior Backend Eng", "salary": "30 LPA"}]}
        ]
        self.engine.deduplicate_city_records(records)
        canonical = records[0]
        titles = {j["title"] for j in canonical["job_openings"]}
        print("\n[Challenge 2a Result] Merged titles:", titles)
        self.assertIn("Senior Backend Eng", titles,
                      "VULNERABILITY DETECTED: Unique job opening without URL was silently dropped!")

    def test_adv_4_dedup_dropping_jobs_with_shared_career_url(self):
        """
        Challenge 2b: Deduplication silently drops unique job openings that share a generic career portal URL.
        """
        records = [
            {"id": 10, "name": "Jar Tech", "city": "Bengaluru", "job_openings": [{"title": "Frontend Eng", "url": "https://company.com/careers"}]},
            {"id": 20, "name": "Jar Tech Pvt Ltd", "city": "Bengaluru", "job_openings": [{"title": "Data Scientist", "url": "https://company.com/careers"}]}
        ]
        self.engine.deduplicate_city_records(records)
        canonical = records[0]
        titles = {j["title"] for j in canonical["job_openings"]}
        print("\n[Challenge 2b Result] Merged titles with shared URL:", titles)
        self.assertIn("Data Scientist", titles,
                      "VULNERABILITY DETECTED: Unique job opening sharing career URL was silently dropped!")

    def test_adv_5_dedup_address_guardrail_overwrite(self):
        """
        Challenge 2c: Deduplication does not respect address quality when merging;
        a generic address can lock out a verified street address from a duplicate record.
        """
        records = [
            {"id": 1, "name": "Acme Tech", "city": "Bengaluru", "office_address": ""},
            {"id": 2, "name": "Acme Tech Pvt Ltd", "city": "Bengaluru", "office_address": "Bengaluru, India"},
            {"id": 3, "name": "Acme Tech Limited", "city": "Bengaluru", "office_address": "Plot 14, Sector 3, HSR Layout, Bengaluru"}
        ]
        self.engine.deduplicate_city_records(records)
        canonical = records[0]
        print("\n[Challenge 2c Result] Merged office_address:", canonical.get("office_address"))
        self.assertEqual(canonical.get("office_address"), "Plot 14, Sector 3, HSR Layout, Bengaluru",
                         "VULNERABILITY DETECTED: Canonical record inherited generic address and ignored verified street address!")

    def test_adv_6_address_guardrail_without_commas(self):
        """
        Challenge 3a: _is_verified_street_address fails on valid street addresses formatted without commas.
        """
        valid_addr_no_comma = "3rd Floor Tower B DLF Cyber City Gurugram Haryana 122002"
        is_verified = self.engine._is_verified_street_address(valid_addr_no_comma)
        print("\n[Challenge 3a Result] is_verified for no-comma address:", is_verified)
        self.assertTrue(is_verified,
                        "VULNERABILITY DETECTED: Valid street address without commas was not recognized as verified!")

    def test_adv_7_coordinate_bounding_box_unmapped_metro_localities(self):
        """
        Challenge 4a: Cities like Thane, Faridabad, Ghaziabad, and Secunderabad are mapped to Bengaluru
        default center instead of their actual metro city (Mumbai, Delhi NCR, Hyderabad).
        """
        thane_record = {"id": 1, "name": "ThaneStartup", "city": "Thane, Maharashtra", "lat": 19.2183, "lng": 72.9781}
        faridabad_record = {"id": 2, "name": "FaridabadStartup", "city": "Faridabad, Haryana", "lat": 28.4089, "lng": 77.3178}
        records = [thane_record, faridabad_record]

        fixed = self.engine.verify_and_heal_coordinates(records)
        print("\n[Challenge 4a Result] Thane lat/lng after healing:", records[0]["lat"], records[0]["lng"])
        print("Faridabad lat/lng after healing:", records[1]["lat"], records[1]["lng"])
        self.assertEqual(records[0]["lat"], 19.2183,
                         "VULNERABILITY DETECTED: Thane coordinate (Mumbai metro) was wiped out and healed to Bengaluru default!")
        self.assertEqual(records[1]["lat"], 28.4089,
                         "VULNERABILITY DETECTED: Faridabad coordinate (Delhi NCR metro) was wiped out and healed to Bengaluru default!")

    def test_adv_8_tld_healing_in_url_path_or_query_param(self):
        """
        Challenge 1c: Ensure TLD healing regex does not mutate foreign TLD strings
        occurring inside URL paths or query parameters of valid .com/.in domains.
        """
        records = [
            {
                "id": 1,
                "name": "PathTest",
                "website": "https://example.com/file.it/download",
                "logo_domain": "example.com"
            },
            {
                "id": 2,
                "name": "QueryTest",
                "website": "https://example.in/search?country=de&lang=it",
                "logo_domain": "example.in"
            }
        ]
        self.engine.heal_foreign_tlds(records)
        self.assertEqual(
            records[0]["website"],
            "https://example.com/file.it/download",
            "VULNERABILITY DETECTED: '.it' inside URL path segment was wrongly replaced with '.com'!"
        )
        self.assertEqual(
            records[1]["website"],
            "https://example.in/search?country=de&lang=it",
            "VULNERABILITY DETECTED: '.it' inside URL query string was wrongly replaced with '.com'!"
        )

    def test_adv_9_tld_healing_logo_svg_url_and_job_openings(self):
        """
        Challenge 1d: Ensure heal_foreign_tlds correctly heals foreign TLDs in
        logo_svg_url and job_openings[].url / job_url.
        """
        records = [
            {
                "id": 10,
                "name": "ItalyLogo",
                "website": "https://www.italylogo.it",
                "logo_domain": "italylogo.it",
                "logo_svg_url": "https://www.italylogo.it/logo.svg",
                "job_openings": [
                    {"title": "Dev", "url": "https://www.italylogo.it/jobs/1"},
                    {"title": "QA", "job_url": "https://www.italylogo.it/jobs/2"}
                ]
            }
        ]
        healed = self.engine.heal_foreign_tlds(records)
        self.assertEqual(healed, 1)
        self.assertEqual(records[0]["logo_svg_url"], "https://www.italylogo.com/logo.svg")
        self.assertEqual(records[0]["job_openings"][0]["url"], "https://www.italylogo.com/jobs/1")
        self.assertEqual(records[0]["job_openings"][1]["job_url"], "https://www.italylogo.com/jobs/2")

    def test_adv_10_address_guardrail_pincode_generic_address(self):
        """
        Challenge 3b: Ensure _is_verified_street_address returns False for generic city
        names that contain PIN codes (e.g., 'Bengaluru 560001, India').
        """
        generic_with_pin = "Bengaluru 560001, India"
        is_verified = self.engine._is_verified_street_address(generic_with_pin)
        self.assertFalse(
            is_verified,
            "VULNERABILITY DETECTED: Generic city address with PIN code was wrongly classified as verified street address!"
        )

    def test_adv_11_coordinate_bounding_box_exact_boundary_values(self):
        """
        Challenge 4b: Ensure coordinates lying exactly on the minimum or maximum
        lat/lng boundary of CITY_BOUNDS are classified as in-bounds and preserved.
        """
        blr_bounds = CITY_BOUNDS["Bengaluru"]
        min_lat, max_lat = blr_bounds["lat"]
        min_lng, max_lng = blr_bounds["lng"]

        records = [
            {"id": 1, "name": "MinBoundary", "city": "Bengaluru", "lat": min_lat, "lng": min_lng},
            {"id": 2, "name": "MaxBoundary", "city": "Bengaluru", "lat": max_lat, "lng": max_lng}
        ]
        fixed = self.engine.verify_and_heal_coordinates(records)
        self.assertEqual(fixed, 0, "Coordinates exactly on bounding box limits must not be wiped out!")
        self.assertEqual(records[0]["lat"], min_lat)
        self.assertEqual(records[1]["lat"], max_lat)

    def test_adv_12_uppercase_tlds_and_malformed_job_openings(self):
        """
        Challenge 1e: Ensure uppercase foreign TLDs (.IT, .DE) are healed and
        malformed records (non-list job_openings) are handled safely without errors.
        """
        records = [
            {
                "id": 1,
                "name": "UpperTLD",
                "website": "https://www.example.IT",
                "logo_domain": "example.DE",
                "job_openings": "Not a list"
            }
        ]
        healed = self.engine.heal_foreign_tlds(records)
        self.assertEqual(healed, 1)
        self.assertEqual(records[0]["website"], "https://www.example.com")
        self.assertEqual(records[0]["logo_domain"], "example.com")

    def test_adv_13_address_guardrail_multicomma_generic(self):
        """
        Challenge 3c: Ensure _is_verified_street_address returns False for multi-comma
        generic city addresses (e.g., 'Bengaluru, Karnataka, India').
        """
        multicomma = "Bengaluru, Karnataka, India"
        is_verified = self.engine._is_verified_street_address(multicomma)
        self.assertFalse(is_verified, "Multi-comma generic city address was wrongly classified as verified!")


if __name__ == "__main__":
    unittest.main()
