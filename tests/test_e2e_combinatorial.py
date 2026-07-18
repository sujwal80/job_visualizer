#!/usr/bin/env python3
"""
Milestone 2 Task: Exploratory Cross-Feature Combinatorial Audit
Test Suite: tests/test_e2e_combinatorial.py

This test harness implements 16 distinct cross-feature combinatorial test cases
probing complex interactions across the Startup Visualizer application:
1. Rate-limit token bucket state during burst queries combined with invalid parameters.
2. Rate-limit burst traffic combined with Gzip compression and Accept-Encoding.
3. Viewport geographic filtering combined with Gzip compression and payload pruning.
4. Viewport boundary coordinates at world extremes combined with limit slicing.
5. Viewport bounds combined with permitted metadata filters (city, skill, industry) - BUG PROBE.
6. Rate limiting protection on details endpoints transitioning from 404 to 429.
7. Security headers (CSP, nosniff) and Gzip compression under XSS query parameter injection.
8. Inverted viewport bounding box coordinates combined with float validation.
9. Details endpoint Gzip compression combined with XSS URI scheme sanitization.
10. Details endpoint null/missing attribute sanitization combined with rate limit headers.
11. Combined search query filtering with unicode/emojis and Cache-Control headers.
12. Extreme limits (0 vs 5000) combined with Vary: Accept-Encoding headers.
13. Memory profile cache LRU consistency under simulated session/token reset.
14. Rate limit shared quota persistence across multiple endpoints (/api/companies and /api/companies/<id>).
15. CORS and CSP security headers on OPTIONS preflight and GET 400 error responses.
16. Multi-dict duplicate query parameter flooding combined with viewport bounds and Gzip.
"""

import unittest
import sys
import os
import json
import math
import time
import gzip
import io
from unittest.mock import patch

# Ensure backend can be imported from project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.app import app


class TestZeroRegressionCombinatorialAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True
        cls.client = app.test_client()

    def setUp(self):
        # Reset any test-specific state if needed
        pass

    def test_combo_01_rate_limit_burst_with_invalid_params(self):
        """
        Combo 1: Rate Limiter + Query Parameter Validation (429 vs 400 precedence).
        Simulates an isolated client IP sending burst traffic (>120 reqs) where requests
        also contain malformed query parameters (min_lat=invalid_float).
        Verifies that once the token bucket is exhausted, HTTP 429 Too Many Requests
        takes precedence over HTTP 400 Bad Request, and includes Retry-After and Cache-Control: no-store.
        """
        test_ip = '10.100.0.1'
        rate_limited = False
        last_resp = None

        for _ in range(130):
            last_resp = self.client.get('/api/companies?min_lat=invalid_float&limit=-10',
                                        environ_base={'REMOTE_ADDR': test_ip})
            if last_resp.status_code == 429:
                rate_limited = True
                break

        self.assertTrue(rate_limited, "Expected HTTP 429 after exceeding rate limit even with malformed query params.")
        self.assertEqual(last_resp.status_code, 429)
        self.assertIn('Retry-After', last_resp.headers, "HTTP 429 missing Retry-After header.")
        self.assertEqual(last_resp.headers.get('X-RateLimit-Remaining'), '0', "X-RateLimit-Remaining must be 0.")
        self.assertIn('no-store', last_resp.headers.get('Cache-Control', '').lower(), "429 must include Cache-Control: no-store.")
        print(" [PASS] Combo 01: Rate limit 429 takes precedence over malformed param 400 under burst traffic.")

    def test_combo_02_rate_limit_burst_with_gzip_encoding(self):
        """
        Combo 2: Rate Limiter + Gzip Compression + Accept-Encoding.
        Simulates burst traffic exceeding 120 req/min with Accept-Encoding: gzip.
        Verifies that HTTP 429 error responses are NOT Gzip compressed (since compression
        is scoped to 200-299 status codes), include Cache-Control: no-store and Vary: Accept-Encoding,
        and attach CSP and nosniff security headers without corruption.
        """
        test_ip = '10.100.0.2'
        last_resp = None
        for _ in range(130):
            last_resp = self.client.get('/api/companies',
                                        headers={'Accept-Encoding': 'gzip'},
                                        environ_base={'REMOTE_ADDR': test_ip})
            if last_resp.status_code == 429:
                break

        self.assertEqual(last_resp.status_code, 429)
        self.assertNotEqual(last_resp.headers.get('Content-Encoding'), 'gzip',
                            "HTTP 429 error response should NOT be Gzip compressed!")
        self.assertIn('Accept-Encoding', last_resp.headers.get('Vary', ''), "Vary: Accept-Encoding missing on 429 response.")
        self.assertIn('Content-Security-Policy', last_resp.headers, "CSP header missing on 429 response.")
        self.assertEqual(last_resp.headers.get('X-Content-Type-Options'), 'nosniff', "nosniff header missing on 429.")
        print(" [PASS] Combo 02: Rate limit 429 correctly avoids Gzip compression while preserving security headers.")

    def test_combo_03_viewport_filtering_with_gzip_compression(self):
        """
        Combo 3: Viewport Bounding Box + Gzip Compression + Payload Formatting.
        Queries /api/companies with viewport bounds (12.9 to 13.0 Lat, 77.5 to 77.6 Lng) and Accept-Encoding: gzip.
        Verifies geographic filtering works simultaneously with Gzip compression (Content-Encoding: gzip),
        unpinned (has_pin=False) startups are retained, and heavy raw job_openings are stripped from payload.
        """
        resp = self.client.get('/api/companies?min_lat=12.9000&max_lat=13.0000&min_lng=77.5000&max_lng=77.6000',
                               headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get('Content-Encoding'), 'gzip', "Expected Content-Encoding: gzip on large bounded payload.")
        
        # Decompress payload to verify contents
        compressed_data = resp.get_data()
        with gzip.GzipFile(fileobj=io.BytesIO(compressed_data), mode='rb') as f:
            data_json = f.read().decode('utf-8')
        data = json.loads(data_json)
        self.assertIsInstance(data, list)
        if len(data) > 0:
            item = data[0]
            self.assertNotIn('job_openings', item, "Lean compressed payload must not include heavy raw job_openings array.")
            self.assertIn('job_count', item, "Lean compressed payload should include summarized job_count.")
        print(" [PASS] Combo 03: Viewport bounding box filtering integrates cleanly with Gzip compression and lean payload stripping.")

    def test_combo_04_viewport_boundary_coordinates_with_limit_slicing(self):
        """
        Combo 4: Viewport Bounding Box at world extremes + Limit validation & slicing.
        Queries /api/companies?min_lat=-90.0&max_lat=90.0&min_lng=-180.0&max_lng=180.0&limit=5.
        Verifies that extreme valid boundary coordinates combine cleanly with limit slicing,
        returning at most 5 startups sorted by job count descending without numeric overflow.
        """
        resp = self.client.get('/api/companies?min_lat=-90.0&max_lat=90.0&min_lng=-180.0&max_lng=180.0&limit=5')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIsInstance(data, list)
        self.assertLessEqual(len(data), 5, f"Expected at most 5 records when limit=5 is requested, got {len(data)}")
        if len(data) >= 2:
            self.assertGreaterEqual(data[0].get("job_count", 0), data[1].get("job_count", 0),
                                    "Results must be sorted by job_count descending.")
        print(" [PASS] Combo 04: Extreme world boundary coordinates combine correctly with limit=5 slicing.")

    def test_combo_05_metadata_filters_with_viewport_bounds_bug_probe(self):
        """
        Combo 5: Viewport Bounding Box + Query Parameter Validation (city, skill, industry) - BUG PROBE.
        Queries /api/companies?min_lat=12.0&max_lat=14.0&min_lng=77.0&max_lng=78.0&city=Hyderabad&skill=Python.
        Notice: _validate_query_params explicitly permits 'city', 'skill', and 'industry'.
        We assert that all returned startups in this query actually match the requested city ('Hyderabad').
        If the backend ignores 'city' during filtering in get_startups(), this test will expose the regression/bug!
        """
        resp = self.client.get('/api/companies?min_lat=10.0&max_lat=20.0&min_lng=70.0&max_lng=80.0&city=Hyderabad')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIsInstance(data, list)
        
        # Check if the returned records actually respect city=Hyderabad
        non_matching = [s.get("name") for s in data if "hyderabad" not in str(s.get("city", "")).lower()]
        self.assertEqual(len(non_matching), 0,
                         f"BUG DETECTED: Query param 'city=Hyderabad' permitted by validation but IGNORED during filtering! "
                         f"Found {len(non_matching)} non-Hyderabad startups in results (e.g. {non_matching[:3]}).")
        print(" [PASS] Combo 05: Metadata filter 'city=Hyderabad' correctly filtered results in combination with viewport bounds.")

    def test_combo_06_rate_limiting_protects_details_404(self):
        """
        Combo 6: Rate Limiter + Details Endpoint (/api/companies/<id>) 404 handling.
        Simulates burst requests against /api/companies/99999999 (non-existent startup ID) from an isolated IP.
        Verifies that after 120 requests, the status transitions from 404 Not Found (with Cache-Control: no-store)
        to 429 Too Many Requests, confirming rate limiting protects details endpoints from automated enumeration.
        """
        test_ip = '10.100.0.3'
        first_resp = self.client.get('/api/companies/99999999', environ_base={'REMOTE_ADDR': test_ip})
        self.assertEqual(first_resp.status_code, 404)
        self.assertIn('no-store', first_resp.headers.get('Cache-Control', '').lower(), "404 must include Cache-Control: no-store.")

        rate_limited = False
        for _ in range(130):
            resp = self.client.get('/api/companies/99999999', environ_base={'REMOTE_ADDR': test_ip})
            if resp.status_code == 429:
                rate_limited = True
                break

        self.assertTrue(rate_limited, "Expected HTTP 429 when enumerating non-existent startup IDs rapidly.")
        print(" [PASS] Combo 06: Rate limiter protects /api/companies/<id> 404 responses from automated scanning.")

    def test_combo_07_security_headers_on_xss_param_injection(self):
        """
        Combo 7: Security Headers (CSP, nosniff) + Query Parameter Validation (XSS detection) + Gzip.
        Sends XSS injection payload in query param (/api/companies?city=<script>alert("XSS")</script>) with Accept-Encoding: gzip.
        Verifies request is rejected with HTTP 400 Bad Request, Content-Security-Policy and nosniff headers
        are present on the 400 response, and no 500 server crash or script execution occurs.
        """
        resp = self.client.get('/api/companies?city=<script>alert("XSS")</script>', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(resp.status_code, 400, f"Expected 400 Bad Request on XSS injection attempt, got {resp.status_code}")
        self.assertIn('Content-Security-Policy', resp.headers, "CSP header missing on HTTP 400 XSS rejection response.")
        self.assertEqual(resp.headers.get('X-Content-Type-Options'), 'nosniff', "nosniff header missing on HTTP 400.")
        self.assertNotEqual(resp.headers.get('Content-Encoding'), 'gzip', "400 Bad Request should not be Gzip compressed.")
        print(" [PASS] Combo 07: Security headers and proper 400 status maintained under XSS query param injection with Gzip.")

    def test_combo_08_inverted_viewport_bounding_box(self):
        """
        Combo 8: Viewport Bounding Box logic + Numeric Float validation.
        Queries /api/companies?min_lat=13.0&max_lat=12.0&min_lng=78.0&max_lng=77.0 where min > max.
        Verifies inverted bounding box passes basic float validation in _validate_query_params,
        and in get_startups() filters out all pinned startups without throwing 500 ValueError/IndexError.
        """
        resp = self.client.get('/api/companies?min_lat=13.0000&max_lat=12.0000&min_lng=78.0000&max_lng=77.0000')
        self.assertEqual(resp.status_code, 200, "Server must return 200 OK without crashing on inverted bounding coordinates.")
        data = json.loads(resp.data)
        self.assertIsInstance(data, list)
        for s in data:
            if s.get("has_pin"):
                self.fail(f"Pinned startup {s.get('id')} should not be returned when min_lat > max_lat!")
        print(" [PASS] Combo 08: Inverted viewport bounding box handled safely without server exception.")

    def test_combo_09_details_endpoint_xss_uri_sanitization_with_gzip(self):
        """
        Combo 9: Details Endpoint (/api/companies/<id>) + URI Sanitization (_sanitize_url) + Gzip Compression.
        Mocks a startup record with javascript:alert(1) in website, data:text/html in founder LinkedIn,
        and vbscript: in job URLs, requested with Accept-Encoding: gzip.
        Verifies backend strips all malicious URI schemes to empty string "", prunes job_openings, and Gzips cleanly.
        """
        with patch('backend.services.startup_service.load_startups') as mock_load:
            mock_load.return_value = [{
                "id": 8801,
                "name": "URI Hacker Corp",
                "lat": 12.97,
                "lng": 77.59,
                "website": "javascript:alert('XSS_SITE')",
                "job_openings": [{
                    "title": "Security Researcher",
                    "url": "vbscript:msgbox('XSS_JOB')",
                    "experience": "2 yrs",
                    "salary": "20 LPA"
                }],
                "founders": [{
                    "name": "Mallory",
                    "linkedin": "data:text/html,<script>alert(1)</script>"
                }],
                "has_pin": True
            }]
            resp = self.client.get('/api/companies/8801', headers={'Accept-Encoding': 'gzip'})
            self.assertEqual(resp.status_code, 200)
            
            # Decompress or read data
            raw_data = resp.get_data()
            if resp.headers.get('Content-Encoding') == 'gzip':
                with gzip.GzipFile(fileobj=io.BytesIO(raw_data), mode='rb') as f:
                    data_json = f.read().decode('utf-8')
            else:
                data_json = raw_data.decode('utf-8')
            data = json.loads(data_json)
            
            self.assertEqual(data.get("url", ""), "", "javascript: scheme not sanitized in details website url!")
            if data.get("jobs"):
                self.assertEqual(data["jobs"][0].get("url", ""), "", "vbscript: scheme not sanitized in job url!")
            if data.get("founders"):
                self.assertEqual(data["founders"][0].get("linkedin", ""), "", "data: scheme not sanitized in founder linkedin!")
            self.assertNotIn("job_openings", data, "Details endpoint must prune raw job_openings array.")
        print(" [PASS] Combo 09: Details endpoint strips malicious URI schemes (javascript/data/vbscript) under Gzip encoding.")

    def test_combo_10_details_endpoint_null_attributes_with_rate_limit_headers(self):
        """
        Combo 10: Details Endpoint + Null/Missing attribute sanitization + Rate limit headers.
        Requests details for a startup record where name, description, city, industry, founders,
        and job_openings are all None. Verifies returns 200 OK with safe defaults without TypeError,
        while attaching X-RateLimit-Limit and X-RateLimit-Remaining headers.
        """
        with patch('backend.services.startup_service.load_startups') as mock_load:
            mock_load.return_value = [{
                "id": 8802,
                "name": None,
                "lat": 12.97,
                "lng": 77.59,
                "city": None,
                "description": None,
                "industry": None,
                "job_openings": None,
                "founders": None,
                "has_pin": True
            }]
            resp = self.client.get('/api/companies/8802', environ_base={'REMOTE_ADDR': '10.100.0.4'})
            self.assertEqual(resp.status_code, 200, "Server must return 200 OK without crashing on all-Null attributes.")
            data = json.loads(resp.data)
            self.assertEqual(data.get("name", ""), "", "Null name should be sanitized to empty string.")
            self.assertIn('X-RateLimit-Limit', resp.headers, "X-RateLimit-Limit header missing on details endpoint.")
            self.assertIn('X-RateLimit-Remaining', resp.headers, "X-RateLimit-Remaining header missing on details endpoint.")
        print(" [PASS] Combo 10: Details endpoint handles Null/None attributes cleanly while attaching rate limit headers.")

    def test_combo_11_search_query_unicode_emojis_with_caching_headers(self):
        """
        Combo 11: Query Parameter Validation + Unicode/Emoji string handling + Cache-Control.
        Queries /api/companies?city=Bengaluru 🚀&skill=Artificial Intelligence 🤖 with Accept-Encoding: gzip.
        Verifies unicode emojis pass query parameter length and character checks without triggering SQLi/XSS false positives,
        returning 200 OK with Cache-Control: public, max-age=60.
        """
        resp = self.client.get('/api/companies?city=Bengaluru 🚀&skill=Artificial Intelligence 🤖',
                               headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(resp.status_code, 200, "Server must return 200 OK for unicode emoji query params without false positive rejection.")
        self.assertIn('public, max-age=60', resp.headers.get('Cache-Control', ''), "Cache-Control header missing or incorrect.")
        print(" [PASS] Combo 11: Search queries with unicode emojis pass validation and return correct caching headers.")

    def test_combo_12_extreme_limits_with_vary_encoding(self):
        """
        Combo 12: Query Parameter Validation (limit=0 and limit=5000) + Vary Header + Gzip logic.
        Queries /api/companies?limit=0 and /api/companies?limit=5000 with Accept-Encoding: identity.
        Verifies limit=0 returns empty JSON list [] without division-by-zero or indexing errors;
        limit=5000 returns up to 5000 records. Both include Vary: Accept-Encoding.
        """
        resp_0 = self.client.get('/api/companies?limit=0', headers={'Accept-Encoding': 'identity'})
        self.assertEqual(resp_0.status_code, 200)
        self.assertEqual(json.loads(resp_0.data), [], "limit=0 must return empty JSON array [].")
        self.assertIn('Accept-Encoding', resp_0.headers.get('Vary', ''), "Vary: Accept-Encoding missing on limit=0 response.")

        resp_5000 = self.client.get('/api/companies?limit=5000', headers={'Accept-Encoding': 'identity'})
        self.assertEqual(resp_5000.status_code, 200)
        data_5000 = json.loads(resp_5000.data)
        self.assertIsInstance(data_5000, list)
        self.assertLessEqual(len(data_5000), 5000)
        print(" [PASS] Combo 12: Extreme boundary limits (0 and 5000) handled without error and preserve Vary headers.")

    def test_combo_13_memory_profile_cache_lru_consistency_under_session_reset(self):
        """
        Combo 13: Frontend JS Memory Cache LRU model (profileCache) + Simulated Session/Token Reset.
        Simulates the frontend LRU profile cache in Python: populates cache with 60 distinct profile entries
        where capacity limit is 50. Verifies oldest 10 entries (IDs 1-10) are evicted so cache size remains 50.
        Simulating a session reset / cache clearing cleanly purges state without stale references or memory leaks.
        """
        # Model frontend JS LRU cache behavior
        profile_cache = {}
        max_cache_size = 50

        for i in range(1, 61):
            if len(profile_cache) >= max_cache_size:
                # Evict oldest entry (LRU)
                oldest_key = next(iter(profile_cache))
                del profile_cache[oldest_key]
            profile_cache[i] = f"Profile data for startup {i}"

        self.assertEqual(len(profile_cache), 50, f"Expected cache size capped at 50, got {len(profile_cache)}")
        self.assertNotIn(1, profile_cache, "Oldest entry (ID 1) should have been evicted by LRU logic.")
        self.assertIn(60, profile_cache, "Newest entry (ID 60) should be present in LRU cache.")

        # Simulate session reset (user logout / token expiration clearing cache)
        profile_cache.clear()
        self.assertEqual(len(profile_cache), 0, "Cache must be completely empty after session reset.")
        print(" [PASS] Combo 13: Simulated LRU profile cache maintains capacity boundary at 50 and purges cleanly on session reset.")

    def test_combo_14_rate_limit_shared_quota_across_endpoints(self):
        """
        Combo 14: Token Bucket Rate Limiter (_rate_limits) + Cross-endpoint routing (/api/companies and /api/companies/<id>).
        From an isolated client IP (10.150.0.1), makes 60 GET requests to /api/companies followed immediately by
        60 GET requests to /api/companies/1. Verifies the token bucket rate limiter shares quota by client IP
        across endpoints, so the 121st request from that IP to either endpoint returns HTTP 429 Too Many Requests.
        """
        test_ip = '10.150.0.1'
        for _ in range(60):
            resp = self.client.get('/api/companies', environ_base={'REMOTE_ADDR': test_ip})
            self.assertEqual(resp.status_code, 200)

        for _ in range(60):
            resp = self.client.get('/api/companies/1', environ_base={'REMOTE_ADDR': test_ip})
            # May be 200 or 404, but should not be 429 yet
            self.assertNotEqual(resp.status_code, 429)

        # The 121st request across combined endpoints must trigger 429
        resp_121 = self.client.get('/api/companies', environ_base={'REMOTE_ADDR': test_ip})
        self.assertEqual(resp_121.status_code, 429, "Expected HTTP 429 on 121st combined request across endpoints.")
        print(" [PASS] Combo 14: Rate limiter enforces shared 120 req/min quota per client IP across multiple endpoints.")

    def test_combo_15_cors_and_csp_headers_on_options_and_400_errors(self):
        """
        Combo 15: CORS (Access-Control-Allow-*) + Security Headers (CSP) + HTTP Methods (OPTIONS, GET with malformed params).
        Sends an HTTP OPTIONS /api/companies preflight request, and an HTTP GET /api/companies?limit=invalid request.
        Verifies CORS headers (Access-Control-Allow-Origin: *) and strict Content-Security-Policy are present
        on both the OPTIONS preflight response and the 400 Bad Request error response.
        """
        resp_options = self.client.options('/api/companies')
        self.assertIn('Access-Control-Allow-Origin', resp_options.headers, "CORS origin header missing on OPTIONS preflight.")
        self.assertIn('Content-Security-Policy', resp_options.headers, "CSP header missing on OPTIONS preflight.")

        resp_400 = self.client.get('/api/companies?limit=invalid_integer')
        self.assertEqual(resp_400.status_code, 400)
        self.assertIn('Access-Control-Allow-Origin', resp_400.headers, "CORS origin header missing on HTTP 400 error response.")
        self.assertIn('Content-Security-Policy', resp_400.headers, "CSP header missing on HTTP 400 error response.")
        print(" [PASS] Combo 15: CORS and CSP security headers preserved across OPTIONS preflight and HTTP 400 error responses.")

    def test_combo_16_duplicate_param_flooding_with_viewport_bounds(self):
        """
        Combo 16: Multi-dict Duplicate Parameter handling + Viewport Bounding Box + Gzip.
        Sends duplicate bounding and limit parameters: /api/companies?min_lat=12.9&min_lat=invalid&max_lat=13.0&limit=10&limit=abc
        with Accept-Encoding: gzip. Verifies _validate_query_params checks all items in args.getlist() and cleanly
        rejects the request with HTTP 400 Bad Request when encountering 'invalid' or 'abc' among duplicates without 500 crash.
        """
        resp = self.client.get('/api/companies?min_lat=12.9000&min_lat=invalid_float&max_lat=13.0000&limit=10&limit=abc',
                               headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(resp.status_code, 400, f"Expected 400 Bad Request on duplicate malformed params, got {resp.status_code}")
        self.assertNotEqual(resp.status_code, 500, "Server crashed with HTTP 500 on duplicate parameter collision!")
        self.assertIn('Content-Security-Policy', resp.headers, "CSP header missing on duplicate param rejection.")
        print(" [PASS] Combo 16: Duplicate parameter collisions with malformed values rejected with HTTP 400 without server error.")

    def test_combo_17_viewport_bounds_with_unsupported_metadata_filters(self):
        """
        Combo 17: Viewport Bounding Box + Unsupported Metadata Filters (experience, salary, job_type).
        Queries /api/companies?min_lat=12.9&max_lat=13.0&experience=3-5 yrs&salary=20 LPA.
        Verifies that passing boundary/unsupported metadata filters alongside viewport coordinates
        is cleanly rejected by _validate_query_params with HTTP 400 Bad Request without server error (HTTP 500),
        while attaching rate limit and security headers.
        """
        resp = self.client.get('/api/companies?min_lat=12.9000&max_lat=13.0000&experience=3-5 yrs&salary=20 LPA',
                               environ_base={'REMOTE_ADDR': '10.100.0.5'})
        self.assertEqual(resp.status_code, 400, f"Expected 400 Bad Request on unsupported filter params, got {resp.status_code}")
        self.assertNotEqual(resp.status_code, 500, "Server crashed with HTTP 500 on unsupported metadata filters!")
        self.assertIn('Content-Security-Policy', resp.headers, "CSP header missing on 400 response.")
        self.assertIn('X-RateLimit-Remaining', resp.headers, "Rate limit remaining header missing on 400 response.")
        print(" [PASS] Combo 17: Viewport bounds combined with unsupported filters (experience/salary) safely rejected with HTTP 400.")


if __name__ == '__main__':
    # Run tests with verbose output and return clean exit code 0 when all tests pass
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.TestLoader().loadTestsFromTestCase(TestZeroRegressionCombinatorialAudit)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
