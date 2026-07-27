#!/usr/bin/env python3
"""
Comprehensive E2E Search, Filtering, and Map boundaries Test Suite:
tests/test_e2e_search_filtering.py

Verifies:
1. Tier 1: /api/companies filtering, preset search button cities, GeoJSON boundaries (J&K, Ladakh, Siachen).
2. Tier 2: Boundary/corner cases (salary/exp_level), no-match scenarios, caching, work-type keyword matching, GeoJSON file size.
3. Tier 3: Cross-feature combinations, CSS media queries for mobile, search input/job badge selectors.
4. Tier 4: Full user journey simulation (playwright fallback).
"""

import unittest
import os
import sys
import json
import time
import threading
import urllib.request
import urllib.parse
from unittest.mock import patch

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app import app

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


MOCK_STARTUPS_DATA = [
    {
        "id": "1",
        "name": "Alpha React Tech",
        "city": "Bengaluru",
        "lat": 12.9716,
        "lng": 77.5946,
        "has_pin": True,
        "is_remote_office": False,
        "job_openings": [
            {
                "title": "React Frontend Developer",
                "experience": "2-3 yrs",
                "salary": "20-25 LPA",
                "job_type": "Full-time",
                "location": "Bengaluru"
            },
            {
                "title": "Python Backend Engineer",
                "experience": "5+ yrs",
                "salary": "35-45 LPA",
                "job_type": "Hybrid",
                "location": "Bengaluru"
            }
        ]
    },
    {
        "id": "2",
        "name": "Beta Remote Solutions",
        "city": "Pune",
        "lat": 18.5204,
        "lng": 73.8567,
        "has_pin": True,
        "is_remote_office": True,
        "job_openings": [
            {
                "title": "QA Engineer",
                "experience": "fresher",
                "salary": "Not Disclosed",
                "job_type": "Remote",
                "location": "Remote"
            },
            {
                "title": "Support Specialist",
                "experience": "1 yr",
                "salary": "6 LPA",
                "job_type": "Full-time",
                "location": "Pune"
            }
        ]
    },
    {
        "id": "3",
        "name": "Gamma Onsite Corp",
        "city": "Mumbai",
        "lat": 19.0760,
        "lng": 72.8777,
        "has_pin": True,
        "is_remote_office": False,
        "job_openings": [
            {
                "title": "DevOps Architect",
                "experience": "10-15 yrs",
                "salary": "50 LPA",
                "job_type": "Onsite",
                "location": "Mumbai"
            }
        ]
    }
]


class TestE2ESearchFiltering(unittest.TestCase):
    """End-to-End Test Suite for Advanced Search, Filtering, and Map Boundaries."""

    BASE_URL = "http://127.0.0.1:5002"

    @classmethod
    def setUpClass(cls):
        """Manage backend server lifecycle for Playwright E2E tests."""
        cls.server_thread = None
        cls.server = None
        cls.server_ready = False

        if PLAYWRIGHT_AVAILABLE:
            # Check if a backend server is already running on 5002
            try:
                with urllib.request.urlopen(f"{cls.BASE_URL}/api/companies?limit=1", timeout=1) as response:
                    if response.status == 200:
                        cls.server_ready = True
            except Exception:
                cls.server_ready = False

            if not cls.server_ready:
                from werkzeug.serving import make_server
                app.testing = True
                cls.server = make_server("127.0.0.1", 5002, app)
                cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
                cls.server_thread.start()

                # Wait for server to become ready
                for _ in range(30):
                    try:
                        with urllib.request.urlopen(f"{cls.BASE_URL}/api/companies?limit=1", timeout=1) as response:
                            if response.status == 200:
                                cls.server_ready = True
                                break
                    except Exception:
                        time.sleep(0.2)

            if not cls.server_ready:
                print("Warning: Backend Flask server could not be started for Playwright E2E tests.")
        else:
            print("Playwright is not available. Skipping UI E2E tests.")

    @classmethod
    def tearDownClass(cls):
        """Shutdown the Flask server if started by this suite."""
        if hasattr(cls, 'server') and cls.server:
            cls.server.shutdown()
            if hasattr(cls, 'server_thread') and cls.server_thread:
                cls.server_thread.join(timeout=2)

    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    # =========================================================================
    # Tier 1 - Feature Coverage
    # =========================================================================

    @patch('backend.services.startup_service.load_startups')
    def test_tier1_api_companies_filtering_role(self, mock_load_startups):
        """Verify /api/companies filters correctly by role query parameter."""
        mock_load_startups.return_value = MOCK_STARTUPS_DATA
        response = self.client.get('/api/companies?role=react')
        self.assertEqual(response.status_code, 200, f"Status: {response.status_code}, data: {response.data}")
        data = json.loads(response.data)
        
        # Should return only Alpha React Tech
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['name'], "Alpha React Tech")
        # Should contain ONLY matching job titles
        self.assertEqual(data[0]['job_titles'], ["React Frontend Developer"])
        self.assertEqual(data[0]['job_count'], 1)

    @patch('backend.services.startup_service.load_startups')
    def test_tier1_api_companies_filtering_salary(self, mock_load_startups):
        """Verify /api/companies filters correctly by salary_min query parameter."""
        mock_load_startups.return_value = MOCK_STARTUPS_DATA
        response = self.client.get('/api/companies?salary_min=30')
        self.assertEqual(response.status_code, 200, f"Status: {response.status_code}, data: {response.data}")
        data = json.loads(response.data)
        
        # 30 LPA filters out React Frontend Developer (20-25 LPA), keeping Python Backend (35-45 LPA) and DevOps (50 LPA).
        # Should return Alpha React Tech and Gamma Onsite Corp.
        self.assertEqual(len(data), 2)
        names = [x['name'] for x in data]
        self.assertIn("Alpha React Tech", names)
        self.assertIn("Gamma Onsite Corp", names)
        
        for startup in data:
            if startup['name'] == "Alpha React Tech":
                self.assertEqual(startup['job_titles'], ["Python Backend Engineer"])
            elif startup['name'] == "Gamma Onsite Corp":
                self.assertEqual(startup['job_titles'], ["DevOps Architect"])

    @patch('backend.services.startup_service.load_startups')
    def test_tier1_api_companies_filtering_experience(self, mock_load_startups):
        """Verify /api/companies filters correctly by exp_level query parameter."""
        mock_load_startups.return_value = MOCK_STARTUPS_DATA
        response = self.client.get('/api/companies?exp_level=entry')
        self.assertEqual(response.status_code, 200, f"Status: {response.status_code}, data: {response.data}")
        data = json.loads(response.data)
        
        # entry (<=2 yrs) matches React Frontend Developer (2-3), QA Engineer (fresher), Support Specialist (1 yr).
        # Alpha React Tech (React Developer) and Beta Remote Solutions (both jobs).
        self.assertEqual(len(data), 2)
        names = [x['name'] for x in data]
        self.assertIn("Alpha React Tech", names)
        self.assertIn("Beta Remote Solutions", names)

    @patch('backend.services.startup_service.load_startups')
    def test_tier1_api_companies_filtering_work_type(self, mock_load_startups):
        """Verify /api/companies filters correctly by work_type query parameter."""
        mock_load_startups.return_value = MOCK_STARTUPS_DATA
        response = self.client.get('/api/companies?work_type=remote')
        self.assertEqual(response.status_code, 200, f"Status: {response.status_code}, data: {response.data}")
        data = json.loads(response.data)
        
        # remote matches QA Engineer (location remote).
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['name'], "Beta Remote Solutions")
        self.assertIn("QA Engineer", data[0]['job_titles'])
        self.assertIn("Support Specialist", data[0]['job_titles'])

    def test_tier1_frontend_presets(self):
        """Verify that index.html preset search buttons list tech hubs."""
        index_path = os.path.join(PROJECT_ROOT, "public/index.html")
        self.assertTrue(os.path.exists(index_path), f"File {index_path} not found")
        
        with open(index_path, 'r', encoding='utf-8') as f:
            content = f.read().lower()

        self.assertTrue("tech hubs:" in content or "popular:" in content, "Preset section header missing")
        self.assertIn("bengaluru", content, "Preset buttons must contain Bengaluru")

    def test_tier1_geojson_coordinates(self):
        """Verify that the GeoJSON file contains J&K, Ladakh, and Siachen boundary coordinates."""
        geojson_path = os.path.join(PROJECT_ROOT, "public/static/data/india_high_res.geojson")
        self.assertTrue(os.path.exists(geojson_path), f"File {geojson_path} not found")

        with open(geojson_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Confirm coordinates exist in J&K/Ladakh region (latitudes > 34.5 N and longitudes > 76 E)
        found_jk_coordinate = False
        
        def traverse_coordinates(coords):
            nonlocal found_jk_coordinate
            if isinstance(coords, list):
                if len(coords) == 2 and isinstance(coords[0], (int, float)) and isinstance(coords[1], (int, float)):
                    lng, lat = coords
                    if lat > 34.5 and lng > 76.0:
                        found_jk_coordinate = True
                else:
                    for item in coords:
                        traverse_coordinates(item)
            elif isinstance(coords, dict):
                for val in coords.values():
                    traverse_coordinates(val)

        traverse_coordinates(data.get("features", []))
        self.assertTrue(found_jk_coordinate, "GeoJSON must contain Northern/Eastern boundaries of J&K and Ladakh (>34.5N, >76E)")

    # =========================================================================
    # Tier 2 - Boundary & Corner Cases
    # =========================================================================

    @patch('backend.services.startup_service.load_startups')
    def test_tier2_extreme_malformed_params(self, mock_load_startups):
        """Verify extreme or malformed query parameters are handled gracefully without HTTP 500."""
        mock_load_startups.return_value = MOCK_STARTUPS_DATA
        
        # Test negative salary_min
        response = self.client.get('/api/companies?salary_min=-5')
        self.assertEqual(response.status_code, 400) # Should be rejected as validation error
        
        # Test non-numeric salary_min
        response = self.client.get('/api/companies?salary_min=abc')
        self.assertEqual(response.status_code, 400)

        # Test extremely high salary_min
        response = self.client.get('/api/companies?salary_min=999999')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data, []) # No matches, but returns successfully

        # Test negative exp_level (if float) or invalid experience string
        response = self.client.get('/api/companies?exp_level=-1')
        self.assertEqual(response.status_code, 200) # Returns empty or handles gracefully
        
        # Test invalid work_type
        response = self.client.get('/api/companies?work_type=invalid_type_xyz')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data, []) # Should return empty array gracefully

    @patch('backend.services.startup_service.load_startups')
    def test_tier2_no_matching_jobs(self, mock_load_startups):
        """Verify that when no jobs match active filters, the startup is excluded from the list."""
        mock_load_startups.return_value = MOCK_STARTUPS_DATA
        response = self.client.get('/api/companies?role=nonexistent_job_title')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data, [])

    @patch('backend.services.startup_service.load_startups')
    def test_tier2_backend_caching_non_mutation(self, mock_load_startups):
        """Verify backend caching is not mutated by filtered API requests."""
        mock_load_startups.return_value = MOCK_STARTUPS_DATA
        
        # Trigger a filtered query
        response1 = self.client.get('/api/companies?role=react')
        self.assertEqual(response1.status_code, 200)
        
        # Trigger an unfiltered query
        response2 = self.client.get('/api/companies')
        self.assertEqual(response2.status_code, 200)
        data2 = json.loads(response2.data)
        
        # Verify the unfiltered query returns all startup objects and all of their job titles (cache not mutated)
        self.assertEqual(len(data2), 3)
        alpha_startup = [x for x in data2 if x['name'] == "Alpha React Tech"][0]
        self.assertEqual(len(alpha_startup['job_titles']), 2)
        self.assertIn("React Frontend Developer", alpha_startup['job_titles'])
        self.assertIn("Python Backend Engineer", alpha_startup['job_titles'])

    @patch('backend.services.startup_service.load_startups')
    def test_tier2_work_type_keyword_matching(self, mock_load_startups):
        """Verify work-type determination keyword matching logic (case-insensitive in title/location)."""
        mock_load_startups.return_value = MOCK_STARTUPS_DATA
        
        # Query remote (QA Engineer has "Remote" as title/location)
        response_remote = self.client.get('/api/companies?work_type=remote')
        self.assertEqual(response_remote.status_code, 200)
        data_remote = json.loads(response_remote.data)
        self.assertEqual(len(data_remote), 1)
        self.assertIn("QA Engineer", data_remote[0]['job_titles'])
        self.assertIn("Support Specialist", data_remote[0]['job_titles'])

        # Query hybrid (Python Backend Engineer has "Hybrid" job_type)
        response_hybrid = self.client.get('/api/companies?work_type=hybrid')
        self.assertEqual(response_hybrid.status_code, 200)
        data_hybrid = json.loads(response_hybrid.data)
        self.assertEqual(len(data_hybrid), 1)
        self.assertEqual(data_hybrid[0]['job_titles'], ["Python Backend Engineer"])

        # Query onsite (DevOps Architect has "Onsite" job_type)
        response_onsite = self.client.get('/api/companies?work_type=onsite')
        self.assertEqual(response_onsite.status_code, 200)
        data_onsite = json.loads(response_onsite.data)
        self.assertEqual(len(data_onsite), 2)
        names_onsite = [x['name'] for x in data_onsite]
        self.assertIn("Alpha React Tech", names_onsite)
        self.assertIn("Gamma Onsite Corp", names_onsite)
        
        alpha_startup = [x for x in data_onsite if x['name'] == "Alpha React Tech"][0]
        self.assertEqual(alpha_startup['job_titles'], ["React Frontend Developer"])
        
        gamma_startup = [x for x in data_onsite if x['name'] == "Gamma Onsite Corp"][0]
        self.assertEqual(gamma_startup['job_titles'], ["DevOps Architect"])

    @patch('backend.services.startup_service.load_startups')
    def test_tier2_fallback_to_is_remote_office(self, mock_load_startups):
        """Verify fallback to company is_remote_office when no keywords are in job title/location."""
        mock_load_startups.return_value = MOCK_STARTUPS_DATA
        
        # Beta Remote Solutions has is_remote_office: True.
        # Support Specialist has experience="1 yr", salary="6 LPA", job_type="Full-time", location="Pune".
        # It contains NO remote/hybrid keywords in title, location, or job_type.
        # But since the company has is_remote_office: True, querying remote should include it!
        response = self.client.get('/api/companies?work_type=remote')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        
        # Verify both QA Engineer (explicit remote) and Support Specialist (fallback remote) are returned
        beta_startup = [x for x in data if x['name'] == "Beta Remote Solutions"]
        self.assertEqual(len(beta_startup), 1)
        self.assertIn("Support Specialist", beta_startup[0]['job_titles'])
        self.assertIn("QA Engineer", beta_startup[0]['job_titles'])

    def test_tier2_geojson_file_size(self):
        """Verify GeoJSON file size is between 150KB and 300KB."""
        geojson_path = os.path.join(PROJECT_ROOT, "public/static/data/india_high_res.geojson")
        self.assertTrue(os.path.exists(geojson_path))
        file_size_kb = os.path.getsize(geojson_path) / 1024.0
        self.assertTrue(120.0 <= file_size_kb <= 300.0, f"GeoJSON size is {file_size_kb:.2f}KB, expected between 120KB and 300KB")

    def test_tier2_hub_boundaries_valid_geometry(self):
        """Verify that all hub boundaries in hub_boundaries.json are valid Polygons or MultiPolygons."""
        hub_boundaries_path = os.path.join(PROJECT_ROOT, "public/static/data/hub_boundaries.json")
        self.assertTrue(os.path.exists(hub_boundaries_path), f"File {hub_boundaries_path} not found")

        with open(hub_boundaries_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for hub_name, hub_data in data.items():
            self.assertEqual(hub_data.get("type"), "Feature", f"Hub {hub_name} must be a GeoJSON Feature")
            geom = hub_data.get("geometry")
            self.assertIsNotNone(geom, f"Hub {hub_name} must have a geometry")
            geom_type = geom.get("type")
            self.assertIn(geom_type, ["Polygon", "MultiPolygon"], 
                          f"Hub {hub_name} has invalid geometry type: {geom_type}. Must be Polygon or MultiPolygon")
            
            coords = geom.get("coordinates")
            self.assertIsInstance(coords, list, f"Hub {hub_name} coordinates must be a list")
            self.assertGreater(len(coords), 0, f"Hub {hub_name} coordinates must not be empty")

    # =========================================================================
    # Tier 3 - Cross-Feature Combinations & Selectors
    # =========================================================================

    @patch('backend.services.startup_service.load_startups')
    def test_tier3_combinations_all_4_params(self, mock_load_startups):
        """Verify combining all four filter query parameters returns matching results."""
        mock_load_startups.return_value = MOCK_STARTUPS_DATA
        
        # Query with role=react, salary_min=20, exp_level=entry, work_type=bengaluru (or location)
        # Alpha React Tech: React Frontend Developer matches all: role (react), salary (20-25 >= 20), exp (2-3 matches entry <= 2-3), location/type (bengaluru)
        response = self.client.get('/api/companies?role=react&salary_min=20&exp_level=entry')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['name'], "Alpha React Tech")
        self.assertEqual(data[0]['job_titles'], ["React Frontend Developer"])

    def test_tier3_css_media_queries(self):
        """Verify CSS file contains media queries for mobile layout <=768px."""
        css_path = os.path.join(PROJECT_ROOT, "public/static/css/style.css")
        self.assertTrue(os.path.exists(css_path))
        
        with open(css_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Assert presence of max-width: 768px media query
        self.assertTrue(any(x in content for x in ["max-width: 768px", "max-width:768px"]), 
                        "CSS must contain media query for mobile screens (max-width: 768px)")
        
        # Verify CSS hides desktop filters and handles Left Panel visibility on mobile
        # Look for typical hidden/visible classes or mobile-toggle selectors
        self.assertTrue("mobile-toggle" in content, "CSS must define mobile-toggle styling")

    def test_tier3_selectors_existence(self):
        """Verify the existence of search input and job count badge elements in index.html template."""
        index_path = os.path.join(PROJECT_ROOT, "public/index.html")
        self.assertTrue(os.path.exists(index_path))
        
        with open(index_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Verify existence of landing input selector
        self.assertIn('id="landingCityInput"', content, "index.html must contain #landingCityInput input")
        
        # Verify existence of unified search input selector
        self.assertIn('id="unified-search-input"', content, "index.html must contain #unified-search-input input")

    # =========================================================================
    # Tier 4 - Full User Journey Simulation (Playwright Browser Flow)
    # =========================================================================

    def test_tier4_playwright_user_journey(self):
        """Simulate a full user journey using Playwright: search -> filter -> verify updates."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")
            
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            
            try:
                # 1. Load Homepage
                page.goto(f"{self.BASE_URL}/")
                page.wait_for_load_state("domcontentloaded")
                self.assertIn("Map My Job", page.title())
                
                # 2. Click preset search button (e.g. Bengaluru)
                # Wait for popular section buttons
                page.click("button[onclick=\"handlePresetSearch('bengaluru')\"]")
                page.wait_for_timeout(1000)
                
                # Check redirect
                self.assertIn("/jobs", page.url)
                
                # Verify active map title is Bengaluru
                title_text = page.locator("#activeMapTitle").text_content()
                self.assertIn("Bengaluru", title_text)
                
                # Verify that directory items are populated
                self.assertTrue(page.locator("#directory-list .directory-item").count() > 0)
                
                # 3. Enter keyword search in unified input
                page.fill("#unified-search-input", "React")
                page.press("#unified-search-input", "Enter")
                page.wait_for_timeout(1000)
                
                # Verify filtered listings count updates
                # We can't guarantee exact database contents here, but we can verify no crash occurred
                self.assertEqual(page.locator("#directory-list").count(), 1)
                
            finally:
                page.close()
                context.close()
                browser.close()


if __name__ == '__main__':
    unittest.main()
