import unittest
import subprocess
import sys
import os
import json
import math
from unittest.mock import patch

# Ensure backend can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.app import app

class TestProductionAuditE2E(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def test_01_security_headers(self):
        """Verify presence of strict CSP and X-Content-Type-Options headers."""
        response = self.client.get('/api/companies')
        self.assertIn('Content-Security-Policy', response.headers, "CSP header missing!")
        self.assertEqual(response.headers.get('X-Content-Type-Options'), 'nosniff', "X-Content-Type-Options must be nosniff")

    def test_02_rate_limiting_429(self):
        """Verify HTTP 429, Retry-After, and X-RateLimit-Remaining when rate limit is exceeded."""
        test_ip = '10.0.0.88' # Isolated IP to avoid breaking other tests
        rate_limited = False
        last_response = None

        for _ in range(150):
            last_response = self.client.get('/api/companies', environ_base={'REMOTE_ADDR': test_ip})
            if last_response.status_code == 429:
                rate_limited = True
                break

        self.assertTrue(rate_limited, "Expected HTTP 429 Too Many Requests after exceeding limit.")
        data = json.loads(last_response.data)
        self.assertIn("error", data)
        self.assertIn('Retry-After', last_response.headers, "HTTP 429 response missing Retry-After header.")
        self.assertEqual(last_response.headers.get('X-RateLimit-Remaining'), '0', "X-RateLimit-Remaining should be 0 when rate limited.")

    def test_03_query_param_sanitization_400(self):
        """Verify malformed, out-of-bounds, or injection query params return 400 or safe fallback without 500 crash."""
        payloads = [
            '/api/companies?min_lat=invalid_float&limit=abc',
            '/api/companies?min_lat=-999&max_lat=999',
            '/api/companies?city=<script>alert("XSS")</script>',
            '/api/companies?limit=-50',
            '/api/companies?city=Bengaluru\' OR \'1\'=\'1'
        ]
        for url in payloads:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertNotEqual(resp.status_code, 500, f"Server crashed with 500 on malformed input: {url}")
                self.assertIn(resp.status_code, [200, 400], f"Expected 400 Bad Request or 200 safe fallback, got {resp.status_code}")
                if resp.status_code == 200:
                    # Verify safe fallback JSON structure
                    data = json.loads(resp.data)
                    self.assertIsInstance(data, list)

    def test_04_response_optimization_and_caching(self):
        """Verify Gzip compression support, Cache-Control headers, and lean payload structures."""
        # Check caching and lean structure
        resp = self.client.get('/api/companies')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Cache-Control', resp.headers, "Cache-Control header missing on /api/companies")
        
        data = json.loads(resp.data)
        if len(data) > 0:
            item = data[0]
            essential_keys = {'id', 'name', 'lat', 'lng', 'city'}
            self.assertTrue(essential_keys.issubset(item.keys()), f"Payload missing essential keys: {essential_keys - item.keys()}")
            # Verify heavy objects are pruned
            self.assertNotIn('job_openings', item, "Lean payload should not include heavy raw job_openings array")

        # Check Gzip compression when requested
        resp_gzip = self.client.get('/api/companies', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(resp_gzip.headers.get('Content-Encoding'), 'gzip', "Expected Content-Encoding: gzip when requested")

    def test_05_existing_regression_suite(self):
        """Confirm existing unit test suite tests/test_pipeline_regression.py passes 100%."""
        test_script = os.path.abspath(os.path.join(os.path.dirname(__file__), 'test_pipeline_regression.py'))
        result = subprocess.run([sys.executable, test_script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, f"Regression test suite failed!\nOutput:\n{result.stdout}\nErrors:\n{result.stderr}")

    def test_03b_adversarial_nan_inf_floats(self):
        """Verify NaN and Infinity floating point inputs are strictly rejected with HTTP 400."""
        adversarial_floats = [
            '/api/companies?min_lat=nan',
            '/api/companies?max_lat=inf',
            '/api/companies?min_lng=-inf',
            '/api/companies?max_lng=1e308'
        ]
        for url in adversarial_floats:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 400, f"Expected 400 on boundary float: {url}, got {resp.status_code}")

    def test_03c_multidict_duplicate_param_collisions(self):
        """Verify duplicate query parameter collisions do not mask malformed values."""
        duplicate_urls = [
            '/api/companies?limit=10&limit=abc',
            '/api/companies?min_lat=12.97&min_lat=invalid',
            '/api/companies?limit=-10&limit=20'
        ]
        for url in duplicate_urls:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 400, f"Expected 400 on duplicate param collision: {url}, got {resp.status_code}")

    def test_03d_parameter_flooding_and_long_strings(self):
        """Verify long injection payloads and arbitrary parameter flooding are rejected."""
        flooding_urls = [
            '/api/companies?city=' + ('A' * 101),
            '/api/companies?unsupported_flooding_param=' + ('B' * 5000),
            '/api/companies?city=' + '<script>alert("XSS_PAYLOAD_EXCEEDING_ONE_HUNDRED_CHARACTERS_TO_TEST_BOUNDARIES")</script>' * 2
        ]
        for url in flooding_urls:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 400, f"Expected 400 on parameter flooding: {url[:50]}..., got {resp.status_code}")

    def test_06_rate_limit_boundary_zero_limit(self):
        """Verify boundary condition: limit=0 should safely return 429 without throwing 500 IndexError."""
        from backend.utils.rate_limiter import _check_rate_limit
        allowed, retry_after, remaining, limit_val = _check_rate_limit("203.0.113.55", limit=0)
        self.assertFalse(allowed, "Expected allowed=False for limit=0")
        self.assertEqual(remaining, 0)

    def test_07_rate_limit_headers_on_400_error(self):
        """Verify X-RateLimit-* headers are attached even when returning 400 Bad Request."""
        resp = self.client.get('/api/companies?limit=invalid_int', environ_base={'REMOTE_ADDR': '10.0.0.99'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('X-RateLimit-Remaining', resp.headers, "X-RateLimit-Remaining missing on 400 Bad Request")

    def test_08_csp_hardening_directives(self):
        """Verify CSP disallows unsafe-inline and includes object-src and base-uri restrictions."""
        resp = self.client.get('/api/companies')
        csp = resp.headers.get('Content-Security-Policy', '')
        self.assertNotIn("'unsafe-inline'", csp, "CSP should not permit 'unsafe-inline' in production")
        self.assertIn("object-src 'none'", csp, "CSP must restrict object-src")
        self.assertIn("base-uri 'self'", csp, "CSP must restrict base-uri")

    def test_09_xss_uri_scheme_sanitization(self):
        """Verify API endpoints reject or sanitize javascript: and data: URI schemes in links."""
        with patch('backend.services.startup_service.load_startups') as mock_load:
            mock_load.return_value = [{
                "id": 8888,
                "name": "Adversarial AI",
                "lat": 12.9716,
                "lng": 77.5946,
                "city": "Bengaluru",
                "website": "javascript:alert('XSS_WEBSITE')",
                "job_openings": [{
                    "title": "Hacker",
                    "url": "javascript:alert('XSS_JOB')",
                    "experience": "1 yr",
                    "salary": "10 LPA"
                }],
                "founders": [{
                    "name": "Eve",
                    "linkedin": "data:text/html,<script>alert('XSS_FOUNDER')</script>"
                }],
                "has_pin": True
            }]
            resp = self.client.get('/api/companies/8888')
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            
            url_val = data.get("url", "")
            self.assertFalse(url_val.lower().startswith("javascript:"), f"Unsanitized javascript: scheme in website url: {url_val}")
            
            for job in (data.get("jobs", []) or data.get("job_openings", [])):
                job_url = job.get("url", "")
                self.assertFalse(job_url.lower().startswith("javascript:"), f"Unsanitized javascript: scheme in job url: {job_url}")

    def test_10_lean_payload_non_required_fields_handling(self):
        """Verify empty string fields (like industry) are not stripped to prevent UI 'undefined' text."""
        with patch('backend.services.startup_service.load_startups') as mock_load:
            mock_load.return_value = [{
                "id": 7777,
                "name": "EmptyIndustry Corp",
                "lat": 12.9716,
                "lng": 77.5946,
                "city": "Bengaluru",
                "industry": "",
                "verified_email": "",
                "has_pin": True
            }]
            resp = self.client.get('/api/companies')
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertTrue(len(data) > 0)
            item = data[0]
            self.assertIn("industry", item, "Expected 'industry' key to be preserved in payload even when empty.")
            self.assertIsNotNone(item.get("industry"), "Industry should not be None.")

    def test_11_viewport_bounding_box_remote_startups(self):
        """Verify remote startups (has_pin=False) remain discoverable when viewport moves outside Bangalore."""
        with patch('backend.services.startup_service.load_startups') as mock_load:
            mock_load.return_value = [{
                "id": 6666,
                "name": "Remote Only Hub",
                "lat": None,
                "lng": None,
                "city": "San Francisco / Remote",
                "has_pin": False
            }]
            resp = self.client.get('/api/companies?min_lat=18.9&max_lat=19.3&min_lng=72.7&max_lng=73.0')
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            ids = [s["id"] for s in data]
            self.assertIn(6666, ids, "Remote startup excluded when querying viewport bounding box outside Bengaluru!")

    def test_12_gzip_quality_and_identity_headers(self):
        """Verify q=0 rejection and presence of Vary header on uncompressed responses."""
        resp_q0 = self.client.get('/api/companies', headers={'Accept-Encoding': 'gzip;q=0'})
        self.assertNotEqual(resp_q0.headers.get('Content-Encoding'), 'gzip', "Server must not gzip when q=0 is sent!")
        
        resp_identity = self.client.get('/api/companies', headers={'Accept-Encoding': 'identity'})
        self.assertIn('Accept-Encoding', resp_identity.headers.get('Vary', ''), "Vary: Accept-Encoding missing on identity response!")

    def test_13_cache_control_on_errors_and_rate_limits(self):
        """Verify error responses and rate limit errors prevent caching."""
        test_ip = '10.0.0.100'
        last_resp = None
        for _ in range(150):
            last_resp = self.client.get('/api/companies', environ_base={'REMOTE_ADDR': test_ip})
            if last_resp.status_code == 429:
                break
        self.assertEqual(last_resp.status_code, 429)
        self.assertIn('no-store', last_resp.headers.get('Cache-Control', '').lower(), "HTTP 429 must include Cache-Control: no-store")

        resp_404 = self.client.get('/api/companies/999999')
        self.assertIn('no-store', resp_404.headers.get('Cache-Control', '').lower(), "HTTP 404 must include Cache-Control: no-store")

    def test_14_sensitive_and_redundant_attribute_leakage_in_details(self):
        """Verify details endpoint prunes heavy job_openings array and restricts non-required attributes."""
        resp = self.client.get('/api/companies/1')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertNotIn('job_openings', data, "Details endpoint leaked heavy raw job_openings array!")

if __name__ == '__main__':
    unittest.main()
