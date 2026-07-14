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
import socket
import requests
from unittest.mock import patch, MagicMock

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


class TestFlexibleStartupIDLookupAndFallback(unittest.TestCase):
    """Verifies flexible ID endpoint resolution (int/str) and frontend profile fallback."""

    def test_backend_startup_details_flexible_id(self):
        from backend.app import app
        client = app.test_client()
        # Test with numeric string and int
        res_int = client.get("/api/company/1")
        self.assertEqual(res_int.status_code, 200, "Should resolve numeric ID 1")
        data_int = res_int.get_json()
        self.assertIsNotNone(data_int)
        self.assertNotIn("error", data_int)

        res_str = client.get(f"/api/company/{data_int['id']}")
        self.assertEqual(res_str.status_code, 200, "Should resolve string/int ID flexibly")

    def test_frontend_select_and_open_startup_fallback(self):
        js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "static", "js", "modules", "ui_manager.js"))
        with open(js_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("const fallbackStartup = state.startupsData.find(s => String(s.id) === String(id));", content)
        self.assertIn("_processOpenStartup(fallbackStartup);", content)


class TestValidationUtils(unittest.TestCase):
    """Unit tests for check_dns and validate_website_domain with mock patches."""

    @patch('socket.gethostbyname')
    def test_check_dns_success(self, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.3.4'
        from data_acquisition.utils.validation import check_dns
        self.assertTrue(check_dns('example.com'))
        mock_gethostbyname.assert_called_once_with('example.com')

    @patch('socket.gethostbyname')
    def test_check_dns_failure(self, mock_gethostbyname):
        mock_gethostbyname.side_effect = socket.gaierror('mock gaierror')
        from data_acquisition.utils.validation import check_dns
        self.assertFalse(check_dns('invalid-domain.com'))
        mock_gethostbyname.assert_called_once_with('invalid-domain.com')

    @patch('socket.gethostbyname')
    @patch('requests.get')
    @patch('requests.head')
    def test_validate_website_domain_success(self, mock_head, mock_get, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.3.4'
        
        # Mock requests.head success
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.url = 'https://rupeek.com'
        mock_head.return_value = mock_res

        # Mock requests.get for parking page check
        mock_get_res = MagicMock()
        mock_get_res.status_code = 200
        mock_get_res.url = 'https://rupeek.com'
        mock_get_res.text = "Some non-parking HTML content with <body> tag."
        mock_get_res.content = b"Some non-parking HTML content with <body> tag."
        mock_get_res.headers = {}
        mock_get.return_value = mock_get_res

        from data_acquisition.utils.validation import validate_website_domain
        is_active, healed_url, reason = validate_website_domain('https://rupeek.com')
        self.assertTrue(is_active)
        self.assertEqual(healed_url, 'https://rupeek.com')
        self.assertIsNone(reason)
        mock_head.assert_called_once()
        mock_get.assert_called_once()


    @patch('socket.gethostbyname')
    @patch('requests.get')
    @patch('requests.head')
    def test_validate_website_domain_self_healing(self, mock_head, mock_get, mock_gethostbyname):
        # We start with https://www.rupeek.com
        # Primary domain is www.rupeek.com, alt_domain is rupeek.com
        # Mock DNS: www.rupeek.com fails, rupeek.com succeeds
        def dns_side_effect(domain):
            if domain == 'www.rupeek.com':
                raise socket.gaierror('Mock DNS fail')
            return '1.2.3.4'
        mock_gethostbyname.side_effect = dns_side_effect

        # Mock requests for rupeek.com to succeed
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.url = 'https://rupeek.com'
        mock_head.return_value = mock_res

        from data_acquisition.utils.validation import validate_website_domain
        is_active, healed_url, reason = validate_website_domain('https://www.rupeek.com')
        self.assertTrue(is_active)
        self.assertEqual(healed_url, 'https://rupeek.com')
        self.assertIsNone(reason)

    @patch('socket.gethostbyname')
    @patch('requests.get')
    @patch('requests.head')
    def test_validate_website_domain_failure(self, mock_head, mock_get, mock_gethostbyname):
        # kora.ai DNS fails, www.kora.ai DNS fails, and fallback direct request fails
        mock_gethostbyname.side_effect = socket.gaierror('Mock DNS fail')
        
        mock_head.side_effect = requests.exceptions.ConnectionError('Mock connection fail')
        mock_get.side_effect = requests.exceptions.ConnectionError('Mock connection fail')

        from data_acquisition.utils.validation import validate_website_domain
        is_active, healed_url, reason = validate_website_domain('https://kora.ai')
        self.assertFalse(is_active)
        self.assertEqual(healed_url, 'https://kora.ai')
        self.assertIn('Mock connection fail', reason)

    @patch('socket.gethostbyname')
    @patch('requests.get')
    @patch('requests.head')
    def test_validate_website_domain_ssl_fallback_success(self, mock_head, mock_get, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.3.4'
        
        # First call to requests.head with https:// throws SSLError
        # Second call to requests.head with http:// succeeds
        mock_head.side_effect = [
            requests.exceptions.SSLError("HTTPS SSL Error"),
            MagicMock(status_code=200, url="http://rupeek.com", headers={})
        ]
        
        # Mock requests.get for parking page check (which runs on http://rupeek.com)
        mock_get_res = MagicMock()
        mock_get_res.status_code = 200
        mock_get_res.url = 'http://rupeek.com'
        mock_get_res.text = "Some normal site text"
        mock_get_res.content = b"Some normal site text"
        mock_get_res.headers = {}
        mock_get.return_value = mock_get_res

        from data_acquisition.utils.validation import validate_website_domain
        is_active, healed_url, reason = validate_website_domain('https://rupeek.com')
        self.assertTrue(is_active)
        self.assertEqual(healed_url, 'http://rupeek.com')
        self.assertIsNone(reason)

    @patch('socket.gethostbyname')
    @patch('requests.get')
    @patch('requests.head')
    def test_validate_website_domain_ssl_fallback_failure(self, mock_head, mock_get, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.3.4'
        
        # HTTPS throws SSLError, HTTP fallback also fails (e.g. ConnectionError)
        def head_side_effect(url, *args, **kwargs):
            if url.startswith("https://"):
                raise requests.exceptions.SSLError("HTTPS SSL Error")
            else:
                raise requests.exceptions.ConnectionError("HTTP connection failed")
        mock_head.side_effect = head_side_effect
        mock_get.side_effect = requests.exceptions.ConnectionError("HTTP connection failed")


        from data_acquisition.utils.validation import validate_website_domain
        is_active, healed_url, reason = validate_website_domain('https://rupeek.com')
        self.assertFalse(is_active)
        self.assertIn("HTTPS SSL Error", reason)

    @patch('socket.gethostbyname')
    @patch('requests.get')
    @patch('requests.head')
    def test_validate_website_domain_cloudflare_active(self, mock_head, mock_get, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.3.4'
        
        mock_res = MagicMock()
        mock_res.status_code = 403
        mock_res.__bool__.return_value = False
        mock_res.url = 'https://cloudflare-protected.com'
        mock_res.headers = {'Server': 'cloudflare', 'cf-ray': '123456789'}
        mock_head.return_value = mock_res

        from data_acquisition.utils.validation import validate_website_domain
        is_active, healed_url, reason = validate_website_domain('https://cloudflare-protected.com')
        self.assertTrue(is_active)
        self.assertEqual(healed_url, 'https://cloudflare-protected.com')
        # Since it is a cloudflare response on 403, requests.get shouldn't be called for parking page check
        mock_get.assert_not_called()

    @patch('socket.gethostbyname')
    @patch('requests.get')
    def test_check_job_active_cloudflare(self, mock_get, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.3.4'
        
        # Mock requests.get return 403 with Server: cloudflare
        mock_res = MagicMock()
        mock_res.status_code = 403
        mock_res.__bool__.return_value = False
        mock_res.url = 'https://company.com/jobs/123'
        mock_res.headers = {'Server': 'cloudflare'}
        mock_get.return_value = mock_res

        from data_acquisition.utils.validation import check_job_active
        is_active, reason = check_job_active('https://company.com/jobs/123')
        self.assertTrue(is_active)
        self.assertIn("Cloudflare Protection", reason)

    def test_is_parking_page_helper(self):
        from data_acquisition.utils.validation import is_parking_page
        
        # Title matches + short body -> True
        html_short = "<html><head><title>Hostinger - Domain Parked</title></head><body>Short</body></html>"
        self.assertTrue(is_parking_page(html_short))

        # Title matches + long body + no layout -> True
        html_long_no_layout = "<html><head><title>Domain Parked</title></head><body>" + "A" * 3000 + "</body></html>"
        self.assertTrue(is_parking_page(html_long_no_layout))

        # Title matches + long body + layout (container class) -> False
        html_long_layout = "<html><head><title>Domain Parked</title></head><body><div class=\"container\">" + "A" * 3000 + "</div></body></html>"
        self.assertFalse(is_parking_page(html_long_layout))

        # Title does not match -> False
        html_no_match = "<html><head><title>My Real Startup</title></head><body>Short</body></html>"
        self.assertFalse(is_parking_page(html_no_match))

    @patch('socket.gethostbyname')
    @patch('requests.get')
    def test_check_job_active_parking_page(self, mock_get, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.3.4'
        
        # Mock response returning a parking page HTML
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.url = 'https://expired-startup.com/jobs'
        mock_res.headers = {}
        mock_res.text = "<html><head><title>LiteSpeed Cache</title></head><body>Domain is parked.</body></html>"
        mock_res.content = b"<html><head><title>LiteSpeed Cache</title></head><body>Domain is parked.</body></html>"
        mock_get.return_value = mock_res

        from data_acquisition.utils.validation import check_job_active
        is_active, reason = check_job_active('https://expired-startup.com/jobs')
        self.assertFalse(is_active)
        self.assertIn("Parking page detected", reason)

    @patch('requests.head')
    def test_validate_logo_image_success(self, mock_head):
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.headers = {"Content-Type": "image/png"}
        mock_head.return_value = mock_res

        from data_acquisition.utils.validation import validate_logo_image
        self.assertTrue(validate_logo_image("https://startup.com/logo.png"))

    @patch('requests.get')
    @patch('requests.head')
    def test_validate_logo_image_failure_404_403(self, mock_head, mock_get):
        # HEAD returns 403, GET returns 403
        mock_head_res = MagicMock(status_code=403)
        mock_head.return_value = mock_head_res
        
        mock_get_res = MagicMock(status_code=403)
        mock_get_res.__enter__.return_value = mock_get_res
        mock_get.return_value = mock_get_res

        from data_acquisition.utils.validation import validate_logo_image
        self.assertFalse(validate_logo_image("https://startup.com/logo.png"))
        mock_head.assert_called_once()
        mock_get.assert_called_once()

    @patch('requests.head')
    def test_validate_logo_image_failure_non_image(self, mock_head):
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.headers = {"Content-Type": "text/html"}
        mock_head.return_value = mock_res

        from data_acquisition.utils.validation import validate_logo_image
        self.assertFalse(validate_logo_image("https://startup.com/logo.png"))

    @patch('requests.head')
    def test_validate_logo_image_resilient_on_timeout(self, mock_head):
        mock_head.side_effect = requests.exceptions.Timeout("Connection timed out")

        from data_acquisition.utils.validation import validate_logo_image
        # Timeout/Connection errors log warning and return True resiliently
        self.assertTrue(validate_logo_image("https://startup.com/logo.png"))

    @patch('requests.get')
    @patch('requests.head')
    def test_validate_logo_image_head_403_get_200_success(self, mock_head, mock_get):
        mock_head_res = MagicMock(status_code=403)
        mock_head.return_value = mock_head_res

        mock_get_res = MagicMock(status_code=200)
        mock_get_res.headers = {"Content-Type": "image/png"}
        mock_get_res.__enter__.return_value = mock_get_res
        mock_get.return_value = mock_get_res

        from data_acquisition.utils.validation import validate_logo_image
        self.assertTrue(validate_logo_image("https://startup.com/logo.png"))
        mock_head.assert_called_once()
        mock_get.assert_called_once()

    @patch('requests.get')
    @patch('requests.head')
    def test_validate_logo_image_head_405_get_200_success(self, mock_head, mock_get):
        mock_head_res = MagicMock(status_code=405)
        mock_head.return_value = mock_head_res

        mock_get_res = MagicMock(status_code=200)
        mock_get_res.headers = {"Content-Type": "image/jpeg"}
        mock_get_res.__enter__.return_value = mock_get_res
        mock_get.return_value = mock_get_res

        from data_acquisition.utils.validation import validate_logo_image
        self.assertTrue(validate_logo_image("https://startup.com/logo.jpg"))
        mock_head.assert_called_once()
        mock_get.assert_called_once()

    @patch('requests.get')
    @patch('requests.head')
    def test_validate_logo_image_head_403_get_non_image(self, mock_head, mock_get):
        mock_head_res = MagicMock(status_code=403)
        mock_head.return_value = mock_head_res

        mock_get_res = MagicMock(status_code=200)
        mock_get_res.headers = {"Content-Type": "text/html"}
        mock_get_res.__enter__.return_value = mock_get_res
        mock_get.return_value = mock_get_res

        from data_acquisition.utils.validation import validate_logo_image
        self.assertFalse(validate_logo_image("https://startup.com/logo.png"))
        mock_head.assert_called_once()
        mock_get.assert_called_once()

    @patch('requests.get')
    @patch('requests.head')
    def test_validate_logo_image_head_403_get_timeout_resilient(self, mock_head, mock_get):
        mock_head_res = MagicMock(status_code=403)
        mock_head.return_value = mock_head_res

        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out on GET")

        from data_acquisition.utils.validation import validate_logo_image
        self.assertTrue(validate_logo_image("https://startup.com/logo.png"))
        mock_head.assert_called_once()
        mock_get.assert_called_once()

    @patch('requests.get')
    @patch('requests.head')
    def test_validate_logo_image_head_404_no_fallback(self, mock_head, mock_get):
        mock_head_res = MagicMock(status_code=404)
        mock_head.return_value = mock_head_res

        from data_acquisition.utils.validation import validate_logo_image
        self.assertFalse(validate_logo_image("https://startup.com/logo.png"))
        mock_head.assert_called_once()
        mock_get.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
