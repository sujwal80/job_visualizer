#!/usr/bin/env python3
"""
Test Suite: tests/test_unit_modular.py
Verifies that the codebase is structured in a clean, modular architecture
enabling direct unit and E2E testing of domain logic in isolation without HTTP or web server overhead.
"""

import unittest
import sys
import os
import math
import time

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import directly from modular utility and service packages!
from backend.utils.validators import _sanitize_string, _safe_float, _check_has_pin, _sanitize_url, _validate_query_params, _strip_redundant, REQUIRED_FIELDS
from backend.utils.rate_limiter import _check_rate_limit, _rate_limits
from backend.services.startup_service import filter_and_sort_startups, format_startup_summary, format_startup_details


class TestModularValidators(unittest.TestCase):
    """Direct unit tests for pure validation and sanitization helper functions."""
    
    def test_sanitize_string(self):
        self.assertEqual(_sanitize_string(None), "")
        self.assertEqual(_sanitize_string(123), 123)
        self.assertEqual(_sanitize_string("  <script>alert(1)</script>Hello World  "), "alert(1)Hello World")

    def test_safe_float(self):
        self.assertEqual(_safe_float("12.9716"), 12.9716)
        self.assertIsNone(_safe_float("invalid_float"))
        self.assertIsNone(_safe_float("nan"))
        self.assertIsNone(_safe_float("inf"))
        self.assertEqual(_safe_float("nan", default=0.0), 0.0)

    def test_check_has_pin(self):
        # Generic Bangalore city-level coordinates without a street address return False (unpinned/hub)
        self.assertFalse(_check_has_pin({"lat": 12.9716, "lng": 77.5946, "city": "Bengaluru"}))
        # Specific street addresses with distinct coordinates return True
        self.assertTrue(_check_has_pin({"lat": 12.9352, "lng": 77.6245, "address": "Koramangala 4th Block, Bengaluru"}))

    def test_sanitize_url(self):
        self.assertEqual(_sanitize_url("https://worldtech.map"), "https://worldtech.map")
        self.assertEqual(_sanitize_url("javascript:alert(1)"), "")
        self.assertEqual(_sanitize_url("data:text/html,<script>"), "")
        self.assertEqual(_sanitize_url("vbscript:msgbox"), "")

    def test_strip_redundant(self):
        sample = {
            "id": 1,
            "name": "Test AI",
            "lat": float('nan'),
            "lng": 77.59,
            "empty_dict": {},
            "empty_list": [],
            "none_val": None
        }
        cleaned = _strip_redundant(sample)
        self.assertEqual(cleaned["lat"], 0.0)
        self.assertNotIn("empty_dict", cleaned)
        self.assertNotIn("empty_list", cleaned)
        self.assertEqual(cleaned["none_val"], "")  # Converts None to empty string for safe UI rendering


class TestModularRateLimiter(unittest.TestCase):
    """Direct unit tests for the token bucket rate limiter in pure memory."""
    
    def test_rate_limiter_in_memory(self):
        test_ip = "192.0.2.100"
        # Reset any prior state for this IP
        if test_ip in _rate_limits:
            del _rate_limits[test_ip]
            
        # Test quota of 5 requests per 10 seconds
        for i in range(5):
            allowed, retry_after, remaining, limit_val = _check_rate_limit(test_ip, limit=5, window=10)
            self.assertTrue(allowed, f"Request {i+1} should be allowed")
            self.assertEqual(remaining, 5 - (i + 1))
            self.assertEqual(limit_val, 5)
            
        # 6th request must be rate limited
        allowed, retry_after, remaining, limit_val = _check_rate_limit(test_ip, limit=5, window=10)
        self.assertFalse(allowed, "6th request should be blocked by rate limiter")
        self.assertEqual(remaining, 0)
        self.assertGreaterEqual(retry_after, 1)


class TestModularStartupService(unittest.TestCase):
    """Direct unit tests for domain business logic without filesystem or HTTP overhead."""
    
    def setUp(self):
        self.sample_startups = [
            {"id": 1, "name": "AI Corp", "lat": 12.95, "lng": 77.60, "city": "Bengaluru", "industry": "AI", "job_openings": [{"title": "Eng", "skills": ["Python", "PyTorch"]}], "has_pin": True},
            {"id": 2, "name": "Fintech Inc", "lat": 13.05, "lng": 77.70, "city": "Hyderabad", "industry": "Fintech", "job_openings": [], "has_pin": True},
            {"id": 3, "name": "Remote Hub", "lat": None, "lng": None, "city": "Remote", "industry": "SaaS", "job_openings": [{"title": "Dev", "skills": ["React"]}], "has_pin": False}
        ]

    def test_filter_and_sort_startups_by_bounds(self):
        # Query bounds around 12.90 to 13.00 lat should include ID 1 and remote ID 3, excluding ID 2 (13.05)
        res = filter_and_sort_startups(self.sample_startups, 12.90, 13.00, 77.50, 77.65, limit=10)
        ids = [s["id"] for s in res]
        self.assertIn(1, ids)
        self.assertIn(3, ids)
        self.assertNotIn(2, ids)

    def test_filter_by_skill_query(self):
        res = filter_and_sort_startups(self.sample_startups, None, None, None, None, limit=10, skill_query="pytorch")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["id"], 1)

    def test_format_startup_summary(self):
        summary = format_startup_summary(self.sample_startups[0])
        self.assertIn("job_count", summary)
        self.assertEqual(summary["job_count"], 1)
        self.assertIn("skills", summary)
        self.assertIn("Python", summary["skills"])
        self.assertNotIn("job_openings", summary)


class TestFrontendJSModularity(unittest.TestCase):
    """Verifies frontend JavaScript exports modular functions onto window.WorldTechApp."""
    
    def test_js_exports_modular_namespace(self):
        js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend', 'static', 'js', 'app.js'))
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("window.WorldTechApp =", content, "app.js must export window.WorldTechApp for testing.")
        expected_methods = [
            "createElement", "showToast", "safeFetch", "getDomain",
            "checkStartupMatch", "updateDashboardStats", "clearAllMarkers",
            "initializeMarkers", "updateMarkersDiff", "applyFiltering"
        ]
        for method in expected_methods:
            self.assertIn(method, content, f"window.WorldTechApp must export {method}.")


class TestScraperBaseIntegratedValidation(unittest.TestCase):
    """Verifies ScraperBase integrates metadata extraction and job validation."""

    def test_validate_and_enrich_jobs_filters_inactive(self):
        from data_acquisition.job_scrapers.scraper_base import ScraperBase
        from unittest.mock import MagicMock
        
        mock_validator = MagicMock()
        # First job returns active, second returns inactive
        mock_validator._check_job_active.side_effect = [
            (True, "Active"),
            (False, "Expired role")
        ]
        
        base = ScraperBase(validator=mock_validator)
        raw_jobs = [
            {"title": "Senior Python Engineer", "url": "https://example.com/job/1", "description": "Need 4 years experience in Python and AWS."},
            {"title": "Closed Role", "url": "https://example.com/job/2", "description": "Expired"}
        ]
        res = base.validate_and_enrich_jobs(raw_jobs)
        self.assertEqual(len(res), 1, "Only active jobs should be returned by ScraperBase")
        self.assertEqual(res[0]["title"], "Senior Python Engineer")
        self.assertIn("Python", res[0]["skills"])
        self.assertIn("AWS", res[0]["skills"])


if __name__ == '__main__':
    unittest.main(verbosity=2)
