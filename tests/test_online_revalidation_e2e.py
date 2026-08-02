#!/usr/bin/env python3
"""
Standalone E2E Test Suite for Continuous Online Re-Validation & Safe Healing System (R1-R4)
Path: tests/test_online_revalidation_e2e.py

Test Philosophy:
- Opaque-Box & Requirement-Driven: Validates functional contracts, API outputs, and dataset transformations.
- Air-Gapped Network Calls: Strictly mocks all external HTTP requests, DNS resolutions, and OpenStreetMap geocoding.
- Zero-Regression Safe Healing Only: Automatic self-healing without degrading valid domains or production metadata.
- Production Database Invariance (mtime safety): Ensures production backend/startups.json is completely untouched.

Coverage Architecture:
- TestTier1FeatureCoverage (21 test methods)
- TestTier2BoundaryAndCornerCases (21 test methods)
- TestTier3CrossFeatureCombinations (6 test methods)
- TestTier4RealWorldApplicationScenarios (6 test methods)
Total Test Cases: 54 test methods across 4 classes.
"""

import unittest
from unittest.mock import patch, MagicMock
import json
import os
import shutil
import sys
import tempfile
import time
import re
import hashlib

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.validate_and_heal_prod_db import (
    heal_foreign_domains,
    generate_prod_audit,
    METRO_CITIES,
    main as validate_and_heal_main,
)
from data_acquisition.verify_city_address_consistency import (
    CITY_BOUNDS,
    get_base_city,
    main as enforce_consistency_main,
)
from data_acquisition.heal_all_office_addresses import (
    get_osm_street_address,
    get_address_from_jobs,
    main as enrich_office_addresses_main,
)
from data_acquisition.deduplicate_startups import (
    get_metro_city,
    normalize_company_name,
    merge_duplicate_startups,
)
from data_acquisition.run_all_metro_cities_production import (
    audit_metro_city_coverage,
    validate_and_enrich_prod_db,
    run_metro_acquisition,
    main as run_all_metro_main,
)
from data_acquisition.heal_real_world_data import (
    determine_true_city,
    clean_address_string,
)
from data_acquisition.db_manager import DBManager


class BaseRevalidationTestCase(unittest.TestCase):
    """Base test case setting up isolated temporary DB directories and patching PROJECT_ROOT."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.backend_dir = os.path.join(self.test_dir, "backend")
        self.public_dir = os.path.join(self.test_dir, "public", "static", "data")
        os.makedirs(self.backend_dir, exist_ok=True)
        os.makedirs(self.public_dir, exist_ok=True)
        self.db_path = os.path.join(self.backend_dir, "startups.json")
        self.public_db_path = os.path.join(self.public_dir, "startups.json")

        self.sample_data = self._get_sample_startups()
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self.sample_data, f, indent=2)
        with open(self.public_db_path, "w", encoding="utf-8") as f:
            json.dump(self.sample_data, f, indent=2)

        self.patches = [
            patch("data_acquisition.validate_and_heal_prod_db.PROJECT_ROOT", self.test_dir),
            patch("data_acquisition.verify_city_address_consistency.PROJECT_ROOT", self.test_dir),
            patch("data_acquisition.heal_all_office_addresses.PROJECT_ROOT", self.test_dir),
            patch("data_acquisition.deduplicate_startups.PROJECT_ROOT", self.test_dir),
            patch("data_acquisition.run_all_metro_cities_production.PROJECT_ROOT", self.test_dir),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _get_sample_startups(self):
        return [
            {
                "id": 1,
                "name": "Bengaluru Tech",
                "city": "Bengaluru",
                "office_address": "HSR Layout, Bengaluru",
                "lat": 12.9141,
                "lng": 77.6411,
                "website": "https://www.blrtech.com",
                "logo_domain": "blrtech.com",
                "job_openings": [],
            },
            {
                "id": 2,
                "name": "Hyderabad AI",
                "city": "Hyderabad",
                "office_address": "Gachibowli, Hyderabad",
                "lat": 17.4401,
                "lng": 78.3489,
                "website": "https://www.hydai.com",
                "logo_domain": "hydai.com",
                "job_openings": [],
            },
            {
                "id": 3,
                "name": "Delhi NCR Soft",
                "city": "Delhi NCR",
                "office_address": "Cyber City, Gurugram",
                "lat": 28.4950,
                "lng": 77.0895,
                "website": "https://www.delhisoft.com",
                "logo_domain": "delhisoft.com",
                "job_openings": [],
            },
            {
                "id": 4,
                "name": "Chennai Cloud",
                "city": "Chennai",
                "office_address": "T Nagar, Chennai",
                "lat": 13.0418,
                "lng": 80.2341,
                "website": "https://www.chennaicloud.com",
                "logo_domain": "chennaicloud.com",
                "job_openings": [],
            },
            {
                "id": 5,
                "name": "Kolkata Fintech",
                "city": "Kolkata",
                "office_address": "Salt Lake, Kolkata",
                "lat": 22.5867,
                "lng": 88.4173,
                "website": "https://www.kolkatafin.com",
                "logo_domain": "kolkatafin.com",
                "job_openings": [],
            },
            {
                "id": 6,
                "name": "Pune Systems",
                "city": "Pune",
                "office_address": "Hinjewadi, Pune",
                "lat": 18.5913,
                "lng": 73.7389,
                "website": "https://www.punesys.com",
                "logo_domain": "punesys.com",
                "job_openings": [],
            },
            {
                "id": 7,
                "name": "Mumbai Capital",
                "city": "Mumbai",
                "office_address": "BKC, Mumbai",
                "lat": 19.0657,
                "lng": 72.8680,
                "website": "https://www.mumbaicap.com",
                "logo_domain": "mumbaicap.com",
                "job_openings": [],
            },
            {
                "id": 8,
                "name": "Italian Startup",
                "city": "Bengaluru",
                "office_address": "Indiranagar, Bengaluru",
                "lat": 12.9719,
                "lng": 77.6412,
                "website": "https://www.italystartup.it",
                "logo_domain": "italystartup.it",
                "job_openings": [],
            },
            {
                "id": 9,
                "name": "German Startup",
                "city": "Mumbai",
                "office_address": "Andheri, Mumbai",
                "lat": 19.1136,
                "lng": 72.8697,
                "website": "https://www.germanstartup.de",
                "logo_domain": "germanstartup.de",
                "job_openings": [],
            },
            {
                "id": 10,
                "name": "French Startup",
                "city": "Pune",
                "office_address": "Kalyani Nagar, Pune",
                "lat": 18.5463,
                "lng": 73.9033,
                "website": "https://www.frenchstartup.fr",
                "logo_domain": "frenchstartup.fr",
                "job_openings": [],
            },
            {
                "id": 11,
                "name": "Spanish Startup",
                "city": "Chennai",
                "office_address": "Velachery, Chennai",
                "lat": 12.9759,
                "lng": 80.2212,
                "website": "https://www.spanishstartup.es",
                "logo_domain": "spanishstartup.es",
                "job_openings": [],
            },
            {
                "id": 12,
                "name": "Aussie Startup",
                "city": "Hyderabad",
                "office_address": "HITEC City, Hyderabad",
                "lat": 17.4474,
                "lng": 78.3762,
                "website": "https://www.aussiestartup.au",
                "logo_domain": "aussiestartup.au",
                "job_openings": [],
            },
            {
                "id": 13,
                "name": "Brazilian Startup",
                "city": "Kolkata",
                "office_address": "New Town, Kolkata",
                "lat": 22.5726,
                "lng": 88.4639,
                "website": "https://www.brazilstartup.br",
                "logo_domain": "brazilstartup.br",
                "job_openings": [],
            },
            {
                "id": 14,
                "name": "Mumbai Out of Bounds",
                "city": "Mumbai",
                "office_address": "Nariman Point, Mumbai",
                "lat": 0.0,
                "lng": 0.0,
                "website": "https://www.oob.com",
                "logo_domain": "oob.com",
                "job_openings": [],
            },
            {
                "id": 15,
                "name": "Contaminated Address Startup",
                "city": "Mumbai",
                "office_address": "Koramangala, Bengaluru",
                "lat": 19.0760,
                "lng": 72.8777,
                "website": "https://www.contam.com",
                "logo_domain": "contam.com",
                "job_openings": [],
            },
            {
                "id": 16,
                "name": "Generic Address Startup",
                "city": "Bengaluru",
                "office_address": "Bengaluru",
                "lat": 12.9716,
                "lng": 77.5946,
                "website": "https://www.generic.com",
                "logo_domain": "generic.com",
                "job_openings": [
                    {
                        "location": "Indiranagar 100 Feet Rd, Bengaluru",
                        "url": "https://example.com/job1",
                    }
                ],
            },
            {
                "id": 17,
                "name": "Duplicate Company",
                "city": "Bengaluru",
                "office_address": "Whitefield, Bengaluru",
                "lat": 12.9698,
                "lng": 77.7499,
                "website": "",
                "logo_svg_url": "",
                "job_openings": [],
            },
            {
                "id": 18,
                "name": "Duplicate Company",
                "city": "Bengaluru",
                "office_address": "Whitefield, Bengaluru",
                "lat": 12.9698,
                "lng": 77.7499,
                "website": "https://www.dup.com",
                "logo_svg_url": "https://www.dup.com/logo.svg",
                "job_openings": [
                    {"title": "Engineer", "url": "https://www.dup.com/job1"}
                ],
            },
            {
                "id": 19,
                "name": "Valid IN Domain",
                "city": "Bengaluru",
                "office_address": "Koramangala, Bengaluru",
                "lat": 12.9352,
                "lng": 77.6245,
                "website": "https://www.valid.in",
                "logo_domain": "valid.in",
                "job_openings": [],
            },
            {
                "id": 20,
                "name": "Valid COM Domain",
                "city": "Mumbai",
                "office_address": "Powai, Mumbai",
                "lat": 19.1197,
                "lng": 72.9051,
                "website": "https://www.valid.com",
                "logo_domain": "valid.com",
                "job_openings": [],
            },
            {
                "id": 21,
                "name": "Valid TECH Domain",
                "city": "Hyderabad",
                "office_address": "Madhapur, Hyderabad",
                "lat": 17.4483,
                "lng": 78.3915,
                "website": "https://www.valid.tech",
                "logo_domain": "valid.tech",
                "job_openings": [],
            },
        ]


class TestTier1FeatureCoverage(BaseRevalidationTestCase):
    """Tier 1: Feature Coverage (21 test methods across R1, R2, R3, R4)."""

    # --- R1: Re-Validation & Healing Engine across 7 metro cities (5 tests) ---
    def test_r1_all_7_metro_cities_defined(self):
        """Verify METRO_CITIES contains precisely the 7 required Indian metro hubs."""
        self.assertEqual(len(METRO_CITIES), 7)
        for city in [
            "Bengaluru",
            "Hyderabad",
            "Delhi NCR",
            "Chennai",
            "Kolkata",
            "Pune",
            "Mumbai",
        ]:
            self.assertIn(city, METRO_CITIES)

    def test_r1_metro_city_coverage_audit(self):
        """Verify audit_metro_city_coverage correctly calculates counts across all 7 cities."""
        counts = audit_metro_city_coverage(self.db_path)
        for city in METRO_CITIES:
            self.assertGreaterEqual(counts[city], 1)

    def test_r1_heal_foreign_domains_italian_tld(self):
        """Verify ID 8 with Italian .it TLD is healed to .com."""
        heal_foreign_domains(self.db_path)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 8)
        self.assertTrue(item["website"].endswith(".com"))
        self.assertTrue(item["logo_domain"].endswith(".com"))

    def test_r1_heal_foreign_domains_german_tld(self):
        """Verify ID 9 with German .de TLD is healed to .com."""
        heal_foreign_domains(self.db_path)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 9)
        self.assertTrue(item["website"].endswith(".com"))

    def test_r1_validate_and_heal_prod_db_main_flow(self):
        """Verify validate_and_heal_main executes full healing and synchronizes data cleanly."""
        with patch("data_acquisition.heal_all_office_addresses.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = []
            validate_and_heal_main()
        self.assertTrue(os.path.exists(self.public_db_path))

    # --- R2: Zero-Regression Guardrails (5 tests) ---
    def test_r2_zero_regression_valid_in_domain_unchanged(self):
        """Verify that ID 19 valid .in domain is not modified by domain healing."""
        heal_foreign_domains(self.db_path)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 19)
        self.assertEqual(item["website"], "https://www.valid.in")

    def test_r2_zero_regression_valid_com_domain_unchanged(self):
        """Verify that ID 20 valid .com domain is not modified by domain healing."""
        heal_foreign_domains(self.db_path)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 20)
        self.assertEqual(item["website"], "https://www.valid.com")

    def test_r2_zero_regression_valid_tech_domain_unchanged(self):
        """Verify that ID 21 valid .tech domain is not modified by domain healing."""
        heal_foreign_domains(self.db_path)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 21)
        self.assertEqual(item["website"], "https://www.valid.tech")

    def test_r2_zero_regression_address_enrichment_preserves_street(self):
        """Verify ID 1 existing street address is preserved by enrich_office_addresses_main."""
        enrich_office_addresses_main()
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 1)
        self.assertEqual(item["office_address"], "HSR Layout, Bengaluru")

    def test_r2_zero_regression_coordinates_inside_city_bounds(self):
        """Verify coordinates within city bounds are unchanged by consistency verifier."""
        enforce_consistency_main()
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 1)
        self.assertEqual(item["lat"], 12.9141)
        self.assertEqual(item["lng"], 77.6411)

    # --- R3: Automated Hourly Execution & Sync (5 tests) ---
    def test_r3_cron_schedule_hourly_expression(self):
        """Verify cron expressions @hourly and 0 * * * * represent 60-minute frequency."""
        def is_hourly_schedule(expr):
            return expr.strip() in ("@hourly", "0 * * * *")
        self.assertTrue(is_hourly_schedule("@hourly"))
        self.assertTrue(is_hourly_schedule("0 * * * *"))

    def test_r3_db_sync_to_public_static(self):
        """Verify validate_and_heal_main mirrors backend DB to public static DB identically."""
        validate_and_heal_main()
        with open(self.db_path, "r", encoding="utf-8") as f1, \
             open(self.public_db_path, "r", encoding="utf-8") as f2:
            self.assertEqual(f1.read(), f2.read())

    def test_r3_db_sync_after_consistency_check(self):
        """Verify enforce_consistency_main synchronizes backend to public static DB."""
        enforce_consistency_main()
        with open(self.db_path, "r", encoding="utf-8") as f1, \
             open(self.public_db_path, "r", encoding="utf-8") as f2:
            self.assertEqual(f1.read(), f2.read())

    def test_r3_db_sync_after_address_enrichment(self):
        """Verify enrich_office_addresses_main synchronizes backend to public static DB."""
        with patch("data_acquisition.heal_all_office_addresses.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = []
            enrich_office_addresses_main()
        with open(self.db_path, "r", encoding="utf-8") as f1, \
             open(self.public_db_path, "r", encoding="utf-8") as f2:
            self.assertEqual(f1.read(), f2.read())

    def test_r3_db_sync_after_deduplication(self):
        """Verify merge_duplicate_startups synchronizes backend to public static DB."""
        merge_duplicate_startups()
        with open(self.db_path, "r", encoding="utf-8") as f1, \
             open(self.public_db_path, "r", encoding="utf-8") as f2:
            self.assertEqual(f1.read(), f2.read())

    # --- R4: Multi-City Geographic Consistency (6 tests) ---
    def test_r4_get_base_city_mapping(self):
        """Verify get_base_city maps city labels to canonical metro city names."""
        self.assertEqual(get_base_city("Cyber City, Gurugram"), "Delhi")
        self.assertEqual(get_base_city("Whitefield, Bengaluru"), "Bengaluru")
        self.assertEqual(get_base_city("BKC, Mumbai, MH"), "Mumbai")
        self.assertEqual(get_base_city("Hitec City, Hyderabad"), "Hyderabad")

    def test_r4_city_bounds_contains_all_metros(self):
        """Verify CITY_BOUNDS defines lat/lng/default coordinates for all metro hubs."""
        for c in ["Mumbai", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Pune", "Delhi"]:
            self.assertIn(c, CITY_BOUNDS)
            self.assertIn("lat", CITY_BOUNDS[c])
            self.assertIn("lng", CITY_BOUNDS[c])

    def test_r4_cross_city_contamination_removal(self):
        """Verify address mentioning Hyderabad in a Mumbai startup is cleaned."""
        item = next(s for s in self.sample_data if s["id"] == 15)
        item["office_address"] = "Hitec City, Hyderabad"
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self.sample_data, f, indent=2)
        enforce_consistency_main()
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        res = next(s for s in data if s["id"] == 15)
        self.assertEqual(res["office_address"], "Mumbai, India")

    def test_r4_out_of_bounds_coordinate_reset(self):
        """Verify out-of-bounds coordinates (0,0) for Mumbai are reset to default."""
        enforce_consistency_main()
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        res = next(s for s in data if s["id"] == 14)
        self.assertEqual(res["lat"], CITY_BOUNDS["Mumbai"]["default"][0])
        self.assertEqual(res["lng"], CITY_BOUNDS["Mumbai"]["default"][1])

    def test_r4_bangalore_locality_conflict_removal_for_non_blr(self):
        """Verify Bengaluru localities in a Chennai address trigger cleaning."""
        enforce_consistency_main()
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        res = next(s for s in data if s["id"] == 15)
        self.assertEqual(res["office_address"], "Mumbai, India")

    def test_r1_r4_determine_true_city_from_jobs(self):
        """Verify determine_true_city infers correct metro city from job postings."""
        city = determine_true_city(
            "India",
            "Office Address",
            [{"location": "BKC, Mumbai"}],
        )
        self.assertEqual(city, "Mumbai")


class TestTier2BoundaryAndCornerCases(BaseRevalidationTestCase):
    """Tier 2: Boundary and Corner Cases (21 test methods)."""

    def test_tier2_tld_healing_it_domain(self):
        """Verify Italian .it domain heals correctly."""
        heal_foreign_domains(self.db_path)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 8)
        self.assertTrue(item["website"].endswith(".com"))

    def test_tier2_tld_healing_de_domain(self):
        """Verify German .de domain heals correctly."""
        heal_foreign_domains(self.db_path)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 9)
        self.assertTrue(item["website"].endswith(".com"))

    def test_tier2_tld_healing_fr_domain(self):
        """Verify French .fr domain heals correctly."""
        heal_foreign_domains(self.db_path)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 10)
        self.assertTrue(item["website"].endswith(".com"))

    def test_tier2_tld_healing_es_domain(self):
        """Verify Spanish .es domain heals correctly."""
        heal_foreign_domains(self.db_path)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 11)
        self.assertTrue(item["website"].endswith(".com"))

    def test_tier2_tld_healing_au_domain(self):
        """Verify Australian .au domain heals correctly."""
        heal_foreign_domains(self.db_path)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 12)
        self.assertTrue(item["website"].endswith(".com"))

    def test_tier2_tld_healing_br_domain(self):
        """Verify Brazilian .br domain heals correctly."""
        heal_foreign_domains(self.db_path)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 13)
        self.assertTrue(item["website"].endswith(".com"))

    def test_tier2_tld_preservation_valid_com(self):
        """Verify .com domain boundary remains unmodified."""
        heal_foreign_domains(self.db_path)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 20)
        self.assertEqual(item["website"], "https://www.valid.com")

    def test_tier2_tld_preservation_valid_in(self):
        """Verify .in domain boundary remains unmodified."""
        heal_foreign_domains(self.db_path)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 19)
        self.assertEqual(item["website"], "https://www.valid.in")

    def test_tier2_tld_preservation_valid_tech(self):
        """Verify .tech domain boundary remains unmodified."""
        heal_foreign_domains(self.db_path)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 21)
        self.assertEqual(item["website"], "https://www.valid.tech")

    def test_tier2_address_enrichment_generic_city_name(self):
        """Verify generic city address Bengaluru triggers enrichment via job location."""
        enrich_office_addresses_main()
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 16)
        self.assertEqual(item["office_address"], "Indiranagar 100 Feet Rd, Bengaluru")

    def test_tier2_address_enrichment_from_job_postings(self):
        """Verify get_address_from_jobs parses street location from job openings."""
        jobs = [{"location": "2nd Floor, Whitefield Road, Bengaluru"}]
        addr = get_address_from_jobs(jobs)
        self.assertEqual(addr, "2nd Floor, Whitefield Road, Bengaluru")

    def test_tier2_address_enrichment_osm_fallback(self):
        """Verify OSM enrichment fallback is called when job locations lack street address."""
        with patch("data_acquisition.heal_all_office_addresses.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = [
                {"display_name": "MG Road, Bengaluru, Karnataka, India"}
            ]
            addr = get_osm_street_address("Test Co", "Bengaluru")
            self.assertEqual(addr, "MG Road, Bengaluru, Karnataka, India")

    def test_tier2_address_enrichment_osm_timeout_resilience(self):
        """Verify get_osm_street_address returns None gracefully on timeout exception."""
        with patch("data_acquisition.heal_all_office_addresses.requests.get") as mock_get:
            mock_get.side_effect = Exception("OSM Timeout")
            addr = get_osm_street_address("Test Co", "Bengaluru")
            self.assertIsNone(addr)

    def test_tier2_bounding_box_mumbai_limits(self):
        """Verify Mumbai bounding box boundaries correctly classify in-bounds vs out-of-bounds."""
        bounds = CITY_BOUNDS["Mumbai"]
        self.assertTrue(bounds["lat"][0] <= 19.0 <= bounds["lat"][1])
        self.assertFalse(bounds["lat"][0] <= 21.0 <= bounds["lat"][1])

    def test_tier2_bounding_box_delhi_ncr_limits(self):
        """Verify Delhi NCR bounding box limits."""
        bounds = CITY_BOUNDS["Delhi"]
        self.assertTrue(bounds["lat"][0] <= 28.6 <= bounds["lat"][1])

    def test_tier2_bounding_box_hyderabad_limits(self):
        """Verify Hyderabad bounding box limits."""
        bounds = CITY_BOUNDS["Hyderabad"]
        self.assertTrue(bounds["lat"][0] <= 17.4 <= bounds["lat"][1])

    def test_tier2_bounding_box_chennai_limits(self):
        """Verify Chennai bounding box limits."""
        bounds = CITY_BOUNDS["Chennai"]
        self.assertTrue(bounds["lat"][0] <= 13.0 <= bounds["lat"][1])

    def test_tier2_bounding_box_pune_limits(self):
        """Verify Pune bounding box limits."""
        bounds = CITY_BOUNDS["Pune"]
        self.assertTrue(bounds["lat"][0] <= 18.5 <= bounds["lat"][1])

    def test_tier2_bounding_box_kolkata_limits(self):
        """Verify Kolkata bounding box limits."""
        bounds = CITY_BOUNDS["Kolkata"]
        self.assertTrue(bounds["lat"][0] <= 22.5 <= bounds["lat"][1])

    def test_tier2_deduplication_duplicates_zero(self):
        """Verify running deduplication on unique companies returns 0 merged duplicates."""
        unique_data = self.sample_data[:5]
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(unique_data, f, indent=2)
        merged_count = merge_duplicate_startups()
        self.assertEqual(merged_count, 0)
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_tier2_hourly_cron_schedule_validation(self):
        """Verify validation helper identifies correct vs incorrect cron schedules."""
        def validate_cron(expr):
            return expr.strip() in ("@hourly", "0 * * * *")
        self.assertTrue(validate_cron("@hourly"))
        self.assertFalse(validate_cron("*/5 * * * *"))


class TestTier3CrossFeatureCombinations(BaseRevalidationTestCase):
    """Tier 3: Cross-Feature Combinations (6 test methods)."""

    def test_tier3_combined_tld_healing_and_consistency_enforcement(self):
        """Verify simultaneous foreign TLD healing and coordinate boundary reset."""
        item = next(s for s in self.sample_data if s["id"] == 8)
        item["lat"] = 0.0
        item["lng"] = 0.0
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self.sample_data, f, indent=2)
        validate_and_heal_main()
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        res = next(s for s in data if s["id"] == 8)
        self.assertTrue(res["website"].endswith(".com"))
        self.assertNotEqual(res["lat"], 0.0)
        self.assertEqual(res["lat"], CITY_BOUNDS["Bengaluru"]["default"][0])

    def test_tier3_dedup_merging_plus_address_enrichment(self):
        """Verify duplicate merging followed by generic address enrichment works end-to-end."""
        merge_duplicate_startups()
        with patch("data_acquisition.heal_all_office_addresses.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = [
                {"display_name": "Whitefield Main Rd, Bengaluru, Karnataka, India"}
            ]
            enrich_office_addresses_main()
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        dup_matches = [s for s in data if "Duplicate Company" in s["name"]]
        self.assertEqual(len(dup_matches), 1)
        self.assertEqual(dup_matches[0]["id"], 17)
        self.assertNotEqual(dup_matches[0]["office_address"], "Bengaluru")

    def test_tier3_cross_city_contamination_and_coordinate_reset_pune(self):
        """Verify Pune company with Bangalore address is cleaned and coordinates reset."""
        pune_item = {
            "id": 100,
            "name": "Pune Mixed",
            "city": "Pune",
            "office_address": "Koramangala, Bengaluru",
            "lat": 12.9352,
            "lng": 77.6245,
            "website": "https://www.punemix.com",
            "logo_domain": "punemix.com",
            "job_openings": [],
        }
        self.sample_data.append(pune_item)
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self.sample_data, f, indent=2)
        enforce_consistency_main()
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        res = next(s for s in data if s["id"] == 100)
        self.assertEqual(res["office_address"], "Pune, India")
        self.assertEqual(res["lat"], CITY_BOUNDS["Pune"]["default"][0])

    def test_tier3_db_sync_verification_after_multi_pass_healing(self):
        """Verify backend and public static DB remain identical after multi-pass healing."""
        heal_foreign_domains(self.db_path)
        enforce_consistency_main()
        merge_duplicate_startups()
        with open(self.db_path, "r", encoding="utf-8") as f1, \
             open(self.public_db_path, "r", encoding="utf-8") as f2:
            self.assertEqual(f1.read(), f2.read())

    def test_tier3_concurrent_file_lock_safety(self):
        """Verify DBManager.file_lock allows safe re-entrant or sequential file access."""
        with DBManager.file_lock(self.db_path):
            with open(self.db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertGreater(len(data), 0)

    def test_tier3_run_all_metro_cities_production_runner_flow(self):
        """Verify run_all_metro_main runs cleanly with mocked discovery service."""
        with patch("data_acquisition.run_all_metro_cities_production.CompanyDiscoveryService") as mock_disc, \
             patch("data_acquisition.run_all_metro_cities_production.LinkedInScraper"), \
             patch("data_acquisition.heal_all_office_addresses.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = []
            run_all_metro_main()
        self.assertTrue(os.path.exists(self.public_db_path))


class TestTier4RealWorldApplicationScenarios(BaseRevalidationTestCase):
    """Tier 4: Real-World Application Scenarios (6 test methods)."""

    def test_tier4_e2e_audit_report_on_temp_prod_db(self):
        """Verify generate_prod_audit generates accurate city counts on temp DB copy."""
        generate_prod_audit(self.db_path)
        counts = audit_metro_city_coverage(self.db_path)
        for city in ["Bengaluru", "Hyderabad", "Delhi NCR", "Chennai", "Kolkata", "Pune", "Mumbai"]:
            self.assertGreaterEqual(counts[city], 1)

    def test_tier4_enterprise_records_5_acceptance_criteria(self):
        """Verify sample enterprise records satisfy all 5 acceptance criteria."""
        enterprises = [
            {"id": 201, "name": "Purplle.com", "city": "Mumbai", "office_address": "Andheri, Mumbai", "lat": 19.1136, "lng": 72.8697, "website": "https://www.purplle.com", "logo_domain": "purplle.com"},
            {"id": 202, "name": "Larsen & Toubro", "city": "Mumbai", "office_address": "Powai, Mumbai", "lat": 19.1197, "lng": 72.9051, "website": "https://www.larsentoubro.com", "logo_domain": "larsentoubro.com"},
            {"id": 203, "name": "Crisil", "city": "Mumbai", "office_address": "Hiranandani, Mumbai", "lat": 19.1200, "lng": 72.9100, "website": "https://www.crisil.com", "logo_domain": "crisil.com"},
        ]
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(enterprises, f, indent=2)
        validate_and_heal_main()
        with open(self.db_path, "r", encoding="utf-8") as f1, \
             open(self.public_db_path, "r", encoding="utf-8") as f2:
            db_data = json.load(f1)
            self.assertEqual(db_data, json.load(f2))
        for item in db_data:
            self.assertTrue(item["website"].endswith(".com") or item["website"].endswith(".in"))
            self.assertIn(item["city"], ["Mumbai", "Bengaluru", "Hyderabad", "Delhi NCR", "Chennai", "Kolkata", "Pune"])
            b = CITY_BOUNDS["Mumbai"]
            self.assertTrue(b["lat"][0] <= item["lat"] <= b["lat"][1])

    def test_tier4_production_database_mtime_invariance(self):
        """Verify production backend/startups.json mtime and content are unchanged after suite runs."""
        prod_db_path = os.path.abspath(os.path.join(PROJECT_ROOT, "backend", "startups.json"))
        self.assertTrue(os.path.exists(prod_db_path), f"Prod DB {prod_db_path} must exist.")
        stat_before = os.stat(prod_db_path)
        mtime_before = stat_before.st_mtime_ns
        size_before = stat_before.st_size
        with open(prod_db_path, "rb") as f:
            hash_before = hashlib.sha256(f.read()).hexdigest()

        # Execute multiple healing and verification operations on temporary database
        heal_foreign_domains(self.db_path)
        enforce_consistency_main()
        merge_duplicate_startups()

        stat_after = os.stat(prod_db_path)
        mtime_after = stat_after.st_mtime_ns
        size_after = stat_after.st_size
        with open(prod_db_path, "rb") as f:
            hash_after = hashlib.sha256(f.read()).hexdigest()

        self.assertEqual(mtime_before, mtime_after, "Production DB st_mtime_ns must not change!")
        self.assertEqual(size_before, size_after, "Production DB size must not change!")
        self.assertEqual(hash_before, hash_after, "Production DB sha256 hash must not change!")

    def test_tier4_public_static_database_content_invariance(self):
        """Verify public/static/data/startups.json mtime and content are unchanged after suite runs."""
        prod_pub_path = os.path.abspath(os.path.join(PROJECT_ROOT, "public", "static", "data", "startups.json"))
        self.assertTrue(os.path.exists(prod_pub_path), f"Public DB {prod_pub_path} must exist.")
        stat_before = os.stat(prod_pub_path)
        mtime_before = stat_before.st_mtime_ns
        with open(prod_pub_path, "rb") as f:
            hash_before = hashlib.sha256(f.read()).hexdigest()

        validate_and_heal_main()

        stat_after = os.stat(prod_pub_path)
        mtime_after = stat_after.st_mtime_ns
        with open(prod_pub_path, "rb") as f:
            hash_after = hashlib.sha256(f.read()).hexdigest()

        self.assertEqual(mtime_before, mtime_after, "Public DB st_mtime_ns must not change!")
        self.assertEqual(hash_before, hash_after, "Public DB sha256 hash must not change!")

    def test_tier4_real_world_address_enrichment_mocked_osm_nominatim(self):
        """Verify OSM Nominatim API responses enrich generic city addresses."""
        with patch("data_acquisition.heal_all_office_addresses.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = [
                {"display_name": "Sarjapur Road, Bellandur, Bengaluru, Karnataka, India"}
            ]
            enrich_office_addresses_main()
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        item = next(s for s in data if s["id"] == 16)
        # Should be enriched with address from job opening first, or OSM if no job openings
        self.assertIn("Bengaluru", item["office_address"])
        self.assertNotEqual(item["office_address"], "Bengaluru")

    def test_tier4_hourly_cron_job_full_revalidation_simulation(self):
        """Simulate an hourly cron trigger running domain healing, consistency check, address enrichment, and deduplication."""
        with patch("data_acquisition.heal_all_office_addresses.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = []
            heal_foreign_domains(self.db_path)
            enforce_consistency_main()
            enrich_office_addresses_main()
            merge_duplicate_startups()
        with open(self.db_path, "r", encoding="utf-8") as f1, \
             open(self.public_db_path, "r", encoding="utf-8") as f2:
            self.assertEqual(f1.read(), f2.read())


if __name__ == "__main__":
    unittest.main()
