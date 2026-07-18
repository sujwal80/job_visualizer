"""
Verification Suite for Unpinned Behavior of Remote Offices.
Verifies that `is_remote_office: true` results in `has_pin: false` while maintaining original `lat`/`lng` data.
"""

import unittest
import json
import os
import sys
from unittest.mock import patch

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app import app
from backend.services.startup_service import format_lightweight_summary, format_startup_summary

class TestRemoteUnpinnedBehavior(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    @patch('backend.services.startup_service.load_startups')
    def test_remote_office_is_unpinned_but_retains_coordinates(self, mock_load_startups):
        """
        Verify that a startup with `is_remote_office: true` results in `has_pin: false`
        while maintaining its original `lat` and `lng` values in serialized outputs.
        """
        # Mock a database with one remote office in Pune (far from Bangalore)
        mock_data = [
            {
                "id": 999,
                "name": "Pune Remote Tech",
                "lat": 18.5204,
                "lng": 73.8567,
                "city": "Pune",
                "is_remote_office": True,
                "job_openings": [
                    {
                        "title": "Remote Engineer",
                        "department": "Engineering",
                        "source": "LinkedIn"
                    }
                ]
            }
        ]
        
        # Enforce that _check_has_pin is run on load_startups just like real execution
        from backend.utils.validators import _check_has_pin
        for s in mock_data:
            s["has_pin"] = _check_has_pin(s)
            
        mock_load_startups.return_value = mock_data

        # 1. Test /api/companies?has_jobs=true (uses format_lightweight_summary)
        response = self.client.get('/api/companies?has_jobs=true')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data), 1)
        
        company = data[0]
        self.assertFalse(company["has_pin"], "is_remote_office: true must result in has_pin: false")
        self.assertEqual(company["lat"], 18.5204, "Original latitude must be maintained")
        self.assertEqual(company["lng"], 73.8567, "Original longitude must be maintained")

        # 2. Test /api/companies (without has_jobs=true, uses format_startup_summary)
        response_all = self.client.get('/api/companies')
        self.assertEqual(response_all.status_code, 200)
        data_all = response_all.get_json()
        self.assertEqual(len(data_all), 1)
        
        company_all = data_all[0]
        self.assertFalse(company_all["has_pin"], "is_remote_office: true must result in has_pin: false")
        self.assertEqual(company_all["lat"], 18.5204, "Original latitude must be maintained")
        self.assertEqual(company_all["lng"], 73.8567, "Original longitude must be maintained")

if __name__ == "__main__":
    unittest.main()
