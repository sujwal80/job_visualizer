"""
Milestone 2 Backend Verification Suite:
Tests R1 (has_jobs=true active jobs filter & lightweight 9-field summary without limit truncation),
R2 (complete profile details & structured job openings on GET /api/companies/<id>),
R3 (X-Data-Version header attachment on /api/companies and /api/companies/<id>).
"""

import unittest
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.app import app
from backend.services.startup_service import get_data_version, format_lightweight_summary

class TestMilestone2Backend(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def test_01_has_jobs_true_returns_lightweight_summaries_and_excludes_zero_jobs(self):
        """
        R1: Verify /api/companies?has_jobs=true returns only active hiring startups (job_count > 0)
        formatted as lightweight summary objects (exactly 9 keys).
        """
        response = self.client.get('/api/companies?has_jobs=true')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0, "Should return active hiring startups when has_jobs=true")

        expected_keys = {"id", "name", "lat", "lng", "city", "logo_url", "industry", "job_count", "has_pin"}
        for s in data:
            self.assertGreater(s["job_count"], 0, f"Startup {s.get('name')} should have job_count > 0")
            self.assertEqual(set(s.keys()), expected_keys, f"Expected 9 lightweight keys, got {set(s.keys())}")

    def test_02_has_jobs_true_ignores_limit_truncation(self):
        """
        R1: Verify /api/companies?has_jobs=true ignores the limit parameter and returns all active hiring companies.
        """
        full_resp = self.client.get('/api/companies?has_jobs=true')
        full_data = full_resp.get_json()

        # Request with artificial limit=1 combined with has_jobs=true should ignore limit=1
        limited_resp = self.client.get('/api/companies?has_jobs=true&limit=1')
        limited_data = limited_resp.get_json()

        self.assertEqual(len(limited_data), len(full_data), "limit parameter should not truncate results when has_jobs=true")

    def test_03_get_startup_details_returns_complete_profile_and_structured_jobs(self):
        """
        R2: Verify GET /api/companies/<id> returns complete company details and structured job openings (jobs array).
        """
        # Pick an active ID from /api/companies
        list_resp = self.client.get('/api/companies?has_jobs=true')
        startups = list_resp.get_json()
        target_id = startups[0]["id"]

        detail_resp = self.client.get(f'/api/companies/{target_id}')
        self.assertEqual(detail_resp.status_code, 200)
        detail = detail_resp.get_json()

        # Check required full profile fields
        for field in ["id", "name", "city", "description", "industry", "jobs", "job_count"]:
            self.assertIn(field, detail, f"Missing expected detail field: {field}")

        self.assertIsInstance(detail["jobs"], list)
        self.assertEqual(len(detail["jobs"]), detail["job_count"])
        if detail["jobs"]:
            job = detail["jobs"][0]
            for job_field in ["title", "department", "experience", "salary", "job_type", "skills", "location"]:
                self.assertIn(job_field, job, f"Missing job field {job_field} in structured job entry")

    def test_04_x_data_version_header_present_on_list_and_detail_endpoints(self):
        """
        R3: Verify X-Data-Version header is attached to /api/companies and /api/companies/<id> responses,
        matching get_data_version().
        """
        expected_version = get_data_version()
        self.assertNotEqual(expected_version, "", "get_data_version() should return a valid string")

        list_resp = self.client.get('/api/companies')
        self.assertEqual(list_resp.headers.get('X-Data-Version'), expected_version)

        detail_resp = self.client.get('/api/companies/1')
        self.assertEqual(detail_resp.headers.get('X-Data-Version'), expected_version)

        # Also verify Access-Control-Expose-Headers exposes X-Data-Version
        expose_headers = list_resp.headers.get('Access-Control-Expose-Headers', '')
        self.assertIn('X-Data-Version', expose_headers)

if __name__ == '__main__':
    unittest.main()
