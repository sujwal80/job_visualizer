#!/usr/bin/env python3
"""
Test Suite: tests/test_unified_router.py
Verifies that the Unified Routing Layer (UnifiedRequest, UnifiedResponse, UnifiedRouter)
properly routes requests, enforces security, validates inputs, and injects correct security headers.
"""

import unittest
import sys
import os
import json
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.unified_router import UnifiedRequest, UnifiedResponse, UnifiedRouter
from backend.services.auth_service import reset_auth_stores, issue_jwt_token
from backend.utils.rate_limiter import _rate_limits


class TestUnifiedRequestResponse(unittest.TestCase):
    """Test cases for Request and Response adapter classes."""

    def test_request_headers_case_insensitivity(self):
        req = UnifiedRequest(
            method="GET",
            path="/api/test",
            url="http://localhost/api/test",
            headers={"Authorization": "Bearer token123", "x-custom-header": "value"}
        )
        self.assertEqual(req.headers.get("authorization"), "Bearer token123")
        self.assertEqual(req.headers.get("AUTHORIZATION"), "Bearer token123")
        self.assertEqual(req.headers.get("x-custom-header"), "value")
        self.assertEqual(req.headers.get("X-CUSTOM-HEADER"), "value")
        self.assertIsNone(req.headers.get("nonexistent"))

    def test_request_cookies_extraction(self):
        # Case 1: dictionary passed directly
        req1 = UnifiedRequest(
            method="GET",
            path="/api/test",
            url="http://localhost/api/test",
            cookies={"session_token": "token123"}
        )
        self.assertEqual(req1.get_cookie("session_token"), "token123")

        # Case 2: parsed from headers
        req2 = UnifiedRequest(
            method="GET",
            path="/api/test",
            url="http://localhost/api/test",
            headers={"Cookie": "session_token=token456; other_cookie=val"}
        )
        self.assertEqual(req2.get_cookie("session_token"), "token456")
        self.assertEqual(req2.get_cookie("other_cookie"), "val")

    def test_request_query_params(self):
        req = UnifiedRequest(
            method="GET",
            path="/api/test",
            url="http://localhost/api/test",
            query_params={"limit": ["10"], "multi": ["a", "b"]}
        )
        self.assertEqual(req.query_params.get("limit"), "10")
        self.assertEqual(req.query_params.get("limit", type=int), 10)
        self.assertEqual(req.query_params.getlist("multi"), ["a", "b"])
        self.assertEqual(req.query_params.getlist("nonexistent"), [])
        self.assertEqual(req.query_params.get("nonexistent", default="fallback"), "fallback")

    def test_response_set_cookie(self):
        res = UnifiedResponse(body="OK", status=200)
        res.set_cookie(name="test_cookie", value="val123", max_age=3600, httponly=True)
        self.assertEqual(len(res.cookies), 1)
        cookie = res.cookies[0]
        self.assertEqual(cookie["name"], "test_cookie")
        self.assertEqual(cookie["value"], "val123")
        self.assertEqual(cookie["max_age"], 3600)
        self.assertTrue(cookie["httponly"])


class TestUnifiedRouter(unittest.IsolatedAsyncioTestCase):
    """Test suite for the UnifiedRouter class using IsolatedAsyncioTestCase."""

    def setUp(self):
        self.router = UnifiedRouter()
        reset_auth_stores()
        # Clean rate limits for local testing
        _rate_limits.clear()

    @patch('backend.unified_router._check_rate_limit')
    async def test_rate_limiting_bypass_on_testing_localhost(self, mock_rate_limit):
        req = UnifiedRequest(
            method="GET",
            path="/api/company",
            url="http://localhost/api/company",
            testing=True,
            client_ip="127.0.0.1"
        )
        res = await self.router.handle_request(req)
        # Bypasses rate limiter check entirely
        mock_rate_limit.assert_not_called()
        self.assertNotEqual(res.status, 429)

    @patch('backend.unified_router._check_rate_limit')
    async def test_rate_limiting_enforcement(self, mock_rate_limit):
        mock_rate_limit.return_value = (False, 30, 0, 120)  # (allowed, retry_after, remaining, limit)
        req = UnifiedRequest(
            method="GET",
            path="/api/company",
            url="http://localhost/api/company",
            client_ip="192.168.1.5"
        )
        res = await self.router.handle_request(req)
        self.assertEqual(res.status, 429)
        self.assertEqual(res.body, {"error": "Rate limit exceeded. Please try again later."})
        self.assertEqual(res.headers.get("retry-after"), "30")
        self.assertEqual(res.headers.get("x-ratelimit-limit"), "120")
        self.assertEqual(res.headers.get("x-ratelimit-remaining"), "0")

    async def test_invalid_query_params(self):
        req = UnifiedRequest(
            method="GET",
            path="/api/company",
            url="http://localhost/api/company",
            query_params={"invalid_param": "val"},
            testing=True,
            client_ip="127.0.0.1"
        )
        res = await self.router.handle_request(req)
        self.assertEqual(res.status, 400)
        self.assertIn("error", res.body)
        self.assertIn("Unsupported query parameter", res.body["error"])

    @patch('backend.services.startup_service.get_data_version')
    @patch('backend.services.startup_service.load_startups')
    async def test_companies_listing_success(self, mock_load_startups, mock_get_data_version):
        mock_get_data_version.return_value = "1"
        mock_load_startups.return_value = [
            {"id": 1, "name": "AI Corp", "lat": 12.95, "lng": 77.60, "city": "Bengaluru", "experience": "Entry", "salary": "10L", "job_type": "Full-time", "skills": ["Python"], "logo_url": "", "url": "", "description": "", "head_count": 10, "funding_stage": "Seed", "verified_email": "a@a.com", "founder_names": ["A"]}
        ]
        req = UnifiedRequest(
            method="GET",
            path="/api/companies",
            url="http://localhost/api/companies",
            testing=True,
            client_ip="127.0.0.1"
        )
        res = await self.router.handle_request(req)
        self.assertEqual(res.status, 200)
        self.assertEqual(len(res.body), 1)
        self.assertEqual(res.body[0]["name"], "AI Corp")
        # Check security headers
        self.assertIn("content-security-policy", res.headers)
        self.assertEqual(res.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(res.headers.get("x-frame-options"), "SAMEORIGIN")
        self.assertEqual(res.headers.get("x-data-version"), "1")  # mock version matches

    @patch('backend.services.startup_service.load_startups')
    async def test_company_details_success_and_not_found(self, mock_load_startups):
        mock_load_startups.return_value = [
            {"id": "1", "name": "AI Corp", "lat": 12.95, "lng": 77.60, "city": "Bengaluru", "experience": "Entry", "salary": "10L", "job_type": "Full-time", "skills": ["Python"], "logo_url": "", "url": "", "description": "", "head_count": 10, "funding_stage": "Seed", "verified_email": "a@a.com", "founder_names": ["A"], "job_openings": []}
        ]
        
        # Test success details lookup
        req_ok = UnifiedRequest(
            method="GET",
            path="/api/company/1",
            url="http://localhost/api/company/1",
            testing=True,
            client_ip="127.0.0.1"
        )
        res_ok = await self.router.handle_request(req_ok)
        self.assertEqual(res_ok.status, 200)
        self.assertEqual(res_ok.body["name"], "AI Corp")

        # Test 404 details lookup
        req_404 = UnifiedRequest(
            method="GET",
            path="/api/company/999",
            url="http://localhost/api/company/999",
            testing=True,
            client_ip="127.0.0.1"
        )
        res_404 = await self.router.handle_request(req_404)
        self.assertEqual(res_404.status, 404)
        self.assertEqual(res_404.body, {"error": "Startup not found"})

    async def test_auth_google_flow(self):
        req = UnifiedRequest(
            method="GET",
            path="/api/auth/google",
            url="http://localhost/api/auth/google",
            testing=True,
            client_ip="127.0.0.1"
        )
        res = await self.router.handle_request(req)
        self.assertEqual(res.status, 200)
        self.assertIn("auth_url", res.body)
        self.assertIn("state", res.body)
        # Check cookie setup
        self.assertEqual(len(res.cookies), 1)
        cookie = res.cookies[0]
        self.assertEqual(cookie["name"], "oauth_state")
        self.assertEqual(cookie["value"], res.body["state"])

    async def test_auth_callback_flow(self):
        # 1. Generate auth URL to record state in mock session/store
        req_init = UnifiedRequest(
            method="GET",
            path="/api/auth/google",
            url="http://localhost/api/auth/google",
            testing=True,
            client_ip="127.0.0.1"
        )
        res_init = await self.router.handle_request(req_init)
        state = res_init.body["state"]

        # 2. Trigger callback with recorded state and mock code
        req_cb = UnifiedRequest(
            method="GET",
            path="/api/auth/callback",
            url=f"http://localhost/api/auth/callback?state={state}&code=mock_code_user1",
            query_params={"state": [state], "code": ["mock_code_user1"]},
            cookies={"oauth_state": state},
            testing=True,
            client_ip="127.0.0.1"
        )
        res_cb = await self.router.handle_request(req_cb)
        self.assertEqual(res_cb.status, 200)
        self.assertTrue(res_cb.body["authenticated"])
        self.assertEqual(res_cb.body["user"]["email"], "ujwal@worldtech.map")
        self.assertIn("token", res_cb.body)

        # Check session cookie set, and oauth state expired
        cookie_names = [c["name"] for c in res_cb.cookies]
        self.assertIn("session_token", cookie_names)
        self.assertIn("oauth_state", cookie_names)

    async def test_auth_demo_login(self):
        req = UnifiedRequest(
            method="POST",
            path="/api/auth/demo_login",
            url="http://localhost/api/auth/demo_login",
            testing=True,
            client_ip="127.0.0.1"
        )
        res = await self.router.handle_request(req)
        self.assertEqual(res.status, 200)
        self.assertTrue(res.body["authenticated"])
        self.assertEqual(res.body["user"]["name"], "Ujwal Singh")

    async def test_auth_status_logged_in_and_logged_out(self):
        # Logged out status check
        req_out = UnifiedRequest(
            method="GET",
            path="/api/auth/status",
            url="http://localhost/api/auth/status",
            testing=True,
            client_ip="127.0.0.1"
        )
        res_out = await self.router.handle_request(req_out)
        self.assertEqual(res_out.status, 200)
        self.assertFalse(res_out.body["authenticated"])

        # Logged in status check
        token = issue_jwt_token({"sub": "user123", "email": "user@test.com", "name": "Test"})
        req_in = UnifiedRequest(
            method="GET",
            path="/api/auth/status",
            url="http://localhost/api/auth/status",
            cookies={"session_token": token},
            testing=True,
            client_ip="127.0.0.1"
        )
        res_in = await self.router.handle_request(req_in)
        self.assertEqual(res_in.status, 200)
        self.assertTrue(res_in.body["authenticated"])
        self.assertEqual(res_in.body["user"]["email"], "user@test.com")

    async def test_auth_logout(self):
        token = issue_jwt_token({"sub": "user123", "email": "user@test.com", "name": "Test"})
        req = UnifiedRequest(
            method="POST",
            path="/api/auth/logout",
            url="http://localhost/api/auth/logout",
            cookies={"session_token": token},
            testing=True,
            client_ip="127.0.0.1"
        )
        res = await self.router.handle_request(req)
        self.assertEqual(res.status, 200)
        self.assertFalse(res.body["authenticated"])
        
        # Verify token is now blacklisted/revoked
        req_status = UnifiedRequest(
            method="GET",
            path="/api/auth/status",
            url="http://localhost/api/auth/status",
            cookies={"session_token": token},
            testing=True,
            client_ip="127.0.0.1"
        )
        res_status = await self.router.handle_request(req_status)
        self.assertFalse(res_status.body["authenticated"])

    async def test_protected_routes_gated(self):
        # 1. Verify unauthenticated profiles return 401
        req_unauth = UnifiedRequest(
            method="GET",
            path="/api/user/profile",
            url="http://localhost/api/user/profile",
            testing=True,
            client_ip="127.0.0.1"
        )
        res_unauth = await self.router.handle_request(req_unauth)
        self.assertEqual(res_unauth.status, 401)
        self.assertEqual(res_unauth.body, {"error": "Unauthenticated. Missing JWT session token."})

        # 2. Verify authenticated profiles return 200
        token = issue_jwt_token({"sub": "user123", "email": "user@test.com", "name": "Test"})
        req_auth = UnifiedRequest(
            method="GET",
            path="/api/user/profile",
            url="http://localhost/api/user/profile",
            cookies={"session_token": token},
            testing=True,
            client_ip="127.0.0.1"
        )
        res_auth = await self.router.handle_request(req_auth)
        self.assertEqual(res_auth.status, 200)
        self.assertTrue(res_auth.body["authenticated"])
        self.assertEqual(res_auth.body["user"]["sub"], "user123")

    async def test_invalid_paths_return_404(self):
        req = UnifiedRequest(
            method="GET",
            path="/api/nonexistent",
            url="http://localhost/api/nonexistent",
            testing=True,
            client_ip="127.0.0.1"
        )
        res = await self.router.handle_request(req)
        self.assertEqual(res.status, 404)
        self.assertEqual(res.body, {"error": "Not Found"})

    def test_static_inject_security_headers(self):
        headers = {"custom": "val"}
        enriched = UnifiedRouter.inject_security_headers(headers, "/some/path.html")
        self.assertIn("content-security-policy", enriched)
        self.assertIn("unsafe-inline", enriched["content-security-policy"]) # non-API uses unsafe-inline
        self.assertEqual(enriched["x-content-type-options"], "nosniff")
        self.assertEqual(enriched["x-frame-options"], "SAMEORIGIN")

        enriched_api = UnifiedRouter.inject_security_headers(headers, "/api/some-endpoint")
        self.assertNotIn("unsafe-inline", enriched_api["content-security-policy"]) # API avoids unsafe-inline

    @patch('backend.services.startup_service.load_startups')
    async def test_job_query_filters(self, mock_load_startups):
        mock_load_startups.return_value = [
            {
                "id": "1",
                "name": "Dev Startup",
                "lat": 12.95,
                "lng": 77.60,
                "city": "Bengaluru",
                "has_pin": True,
                "job_openings": [
                    {"title": "Senior React Developer", "experience": "3-5 yrs", "salary": "20-30 LPA", "job_type": "Full-time", "location": "Remote"},
                    {"title": "QA Engineer", "experience": "1-3 yrs", "salary": "10-15 LPA", "job_type": "Contract", "location": "Bangalore"}
                ]
            }
        ]

        # 1. Test role filtering
        req_role = UnifiedRequest(
            method="GET",
            path="/api/companies",
            url="http://localhost/api/companies",
            query_params={"role": "react"},
            testing=True
        )
        res_role = await self.router.handle_request(req_role)
        self.assertEqual(res_role.status, 200)
        self.assertEqual(len(res_role.body), 1)
        self.assertEqual(res_role.body[0]["job_count"], 1)
        self.assertEqual(res_role.body[0]["job_titles"], ["Senior React Developer"])

        # 2. Test salary_min filtering
        req_sal = UnifiedRequest(
            method="GET",
            path="/api/companies",
            url="http://localhost/api/companies",
            query_params={"salary_min": "18"},
            testing=True
        )
        res_sal = await self.router.handle_request(req_sal)
        self.assertEqual(res_sal.status, 200)
        self.assertEqual(len(res_sal.body), 1)
        self.assertEqual(res_sal.body[0]["job_titles"], ["Senior React Developer"])

        # 3. Test exp_level filtering (categorical)
        req_exp = UnifiedRequest(
            method="GET",
            path="/api/companies",
            url="http://localhost/api/companies",
            query_params={"exp_level": "entry"},
            testing=True
        )
        res_exp = await self.router.handle_request(req_exp)
        self.assertEqual(res_exp.status, 200)
        self.assertEqual(res_exp.body[0]["job_titles"], ["QA Engineer"])

        # 4. Test work_type filtering
        req_wt = UnifiedRequest(
            method="GET",
            path="/api/companies",
            url="http://localhost/api/companies",
            query_params={"work_type": "remote"},
            testing=True
        )
        res_wt = await self.router.handle_request(req_wt)
        self.assertEqual(res_wt.status, 200)
        self.assertEqual(res_wt.body[0]["job_titles"], ["Senior React Developer"])

        # 5. Test detail view consistency and no cache mutation
        req_detail = UnifiedRequest(
            method="GET",
            path="/api/company/1",
            url="http://localhost/api/company/1",
            query_params={"role": "react"},
            testing=True
        )
        res_detail = await self.router.handle_request(req_detail)
        self.assertEqual(res_detail.status, 200)
        self.assertEqual(len(res_detail.body["jobs"]), 1)
        self.assertEqual(res_detail.body["jobs"][0]["title"], "Senior React Developer")

        # Query detail without filters and check cache wasn't mutated
        req_no_filter = UnifiedRequest(
            method="GET",
            path="/api/company/1",
            url="http://localhost/api/company/1",
            testing=True
        )
        res_no_filter = await self.router.handle_request(req_no_filter)
        self.assertEqual(res_no_filter.status, 200)
        self.assertEqual(len(res_no_filter.body["jobs"]), 2)

    @patch('backend.services.startup_service.load_startups')
    async def test_advanced_filtering_regressions(self, mock_load_startups):
        mock_load_startups.return_value = [
            {
                "id": "1",
                "name": "Tech Startup A",
                "lat": 12.95,
                "lng": 77.60,
                "city": "Bengaluru",
                "has_pin": True,
                "is_remote_office": False,
                "job_openings": [
                    {"title": "React Dev", "experience": "2-3 yrs", "salary": "20-30 LPA", "job_type": "Full-time", "location": "Bengaluru"},
                    {"title": "Intern", "experience": "fresher", "salary": "₹8,000", "job_type": "Full-time", "location": "Bengaluru"}
                ]
            },
            {
                "id": "2",
                "name": "Remote Startup B",
                "lat": 12.95,
                "lng": 77.60,
                "city": "Bengaluru",
                "has_pin": False,
                "is_remote_office": True,
                "job_openings": [
                    {"title": "Support Specialist", "experience": "1 yr", "salary": "6 LPA", "job_type": "Full-time", "location": "Bengaluru"},
                ]
            },
            {
                "id": "3",
                "name": "Hybrid/Onsite Startup C",
                "lat": 12.95,
                "lng": 77.60,
                "city": "Bengaluru",
                "has_pin": True,
                "is_remote_office": False,
                "job_openings": [
                    {"title": "Hybrid Engineer", "experience": "5+ yrs", "salary": "35-45 LPA", "job_type": "Hybrid", "location": "Bengaluru"},
                    {"title": "Onsite Architect", "experience": "10-15 yrs", "salary": "50 LPA", "job_type": "Onsite", "location": "Bengaluru"},
                    {"title": "Mid Dev", "experience": "1-5 yrs", "salary": "15 LPA", "job_type": "Full-time", "location": "Bengaluru"}
                ]
            },
            {
                "id": "4",
                "name": "Remote-First with Onsite Job D",
                "lat": 12.95,
                "lng": 77.60,
                "city": "Bengaluru",
                "has_pin": True,
                "is_remote_office": True,
                "job_openings": [
                    {"title": "Onsite Specialist", "experience": "3 yrs", "salary": "12 LPA", "job_type": "Onsite", "location": "Bengaluru"}
                ]
            }
        ]

        # 1. Test salary_min query against ranges without spaces (salary_min=25)
        req_sal25 = UnifiedRequest(
            method="GET",
            path="/api/companies",
            url="http://localhost/api/companies",
            query_params={"salary_min": "25"},
            testing=True
        )
        res_sal25 = await self.router.handle_request(req_sal25)
        self.assertEqual(res_sal25.status, 200)
        # Should match Tech Startup A (React Dev: max 30) and Hybrid/Onsite Startup C (Hybrid: max 45, Onsite: max 50)
        self.assertEqual(len(res_sal25.body), 2)
        names = [s["name"] for s in res_sal25.body]
        self.assertIn("Tech Startup A", names)
        self.assertIn("Hybrid/Onsite Startup C", names)
        
        # 2. Test absolute INR salary threshold (₹8,000 -> 0.08 LPA)
        # salary_min = 0.05 -> Intern matches
        req_sal_low = UnifiedRequest(
            method="GET",
            path="/api/companies",
            url="http://localhost/api/companies",
            query_params={"salary_min": "0.05"},
            testing=True
        )
        res_sal_low = await self.router.handle_request(req_sal_low)
        self.assertEqual(res_sal_low.status, 200)
        startup_a_low = [s for s in res_sal_low.body if s["name"] == "Tech Startup A"][0]
        self.assertIn("Intern", startup_a_low["job_titles"])

        # salary_min = 0.1 -> Intern excluded
        req_sal_high = UnifiedRequest(
            method="GET",
            path="/api/companies",
            url="http://localhost/api/companies",
            query_params={"salary_min": "0.1"},
            testing=True
        )
        res_sal_high = await self.router.handle_request(req_sal_high)
        self.assertEqual(res_sal_high.status, 200)
        startup_a_high = [s for s in res_sal_high.body if s["name"] == "Tech Startup A"]
        if startup_a_high:
            self.assertNotIn("Intern", startup_a_high[0]["job_titles"])

        # 3. Test fallback to company's is_remote_office=True (work_type=remote)
        req_remote = UnifiedRequest(
            method="GET",
            path="/api/companies",
            url="http://localhost/api/companies",
            query_params={"work_type": "remote"},
            testing=True
        )
        res_remote = await self.router.handle_request(req_remote)
        self.assertEqual(res_remote.status, 200)
        self.assertEqual(len(res_remote.body), 1)
        self.assertEqual(res_remote.body[0]["name"], "Remote Startup B")
        self.assertEqual(res_remote.body[0]["job_titles"], ["Support Specialist"])
        
        # Querying work_type=remote must NOT return 'Remote-First with Onsite Job D'
        names_remote = [s["name"] for s in res_remote.body]
        self.assertNotIn("Remote-First with Onsite Job D", names_remote)

        # 4. Test onsite query excluding hybrid/remote jobs (work_type=onsite)
        req_onsite = UnifiedRequest(
            method="GET",
            path="/api/companies",
            url="http://localhost/api/companies",
            query_params={"work_type": "onsite"},
            testing=True
        )
        res_onsite = await self.router.handle_request(req_onsite)
        self.assertEqual(res_onsite.status, 200)
        self.assertEqual(len(res_onsite.body), 3)
        names_onsite = [s["name"] for s in res_onsite.body]
        self.assertIn("Tech Startup A", names_onsite)
        self.assertIn("Hybrid/Onsite Startup C", names_onsite)
        self.assertIn("Remote-First with Onsite Job D", names_onsite)
        
        # Verify Hybrid Engineer is excluded from Hybrid/Onsite Startup C
        startup_c_onsite = [s for s in res_onsite.body if s["name"] == "Hybrid/Onsite Startup C"][0]
        self.assertNotIn("Hybrid Engineer", startup_c_onsite["job_titles"])
        self.assertIn("Onsite Architect", startup_c_onsite["job_titles"])
        self.assertIn("Mid Dev", startup_c_onsite["job_titles"])
        
        # Verify Onsite Specialist is present in Remote-First with Onsite Job D
        startup_d_onsite = [s for s in res_onsite.body if s["name"] == "Remote-First with Onsite Job D"][0]
        self.assertIn("Onsite Specialist", startup_d_onsite["job_titles"])

        # 5. Test experience level categories: senior (exp_level=senior)
        req_senior = UnifiedRequest(
            method="GET",
            path="/api/companies",
            url="http://localhost/api/companies",
            query_params={"exp_level": "senior"},
            testing=True
        )
        res_senior = await self.router.handle_request(req_senior)
        self.assertEqual(res_senior.status, 200)
        startup_c_senior = [s for s in res_senior.body if s["name"] == "Hybrid/Onsite Startup C"][0]
        self.assertIn("Hybrid Engineer", startup_c_senior["job_titles"]) # 5+ yrs
        self.assertIn("Onsite Architect", startup_c_senior["job_titles"]) # 10-15 yrs
        self.assertNotIn("Mid Dev", startup_c_senior["job_titles"]) # 1-5 yrs (mid)

        # 6. Test experience level categories: mid (exp_level=mid)
        req_mid = UnifiedRequest(
            method="GET",
            path="/api/companies",
            url="http://localhost/api/companies",
            query_params={"exp_level": "mid"},
            testing=True
        )
        res_mid = await self.router.handle_request(req_mid)
        self.assertEqual(res_mid.status, 200)
        startup_c_mid = [s for s in res_mid.body if s["name"] == "Hybrid/Onsite Startup C"][0]
        self.assertNotIn("Hybrid Engineer", startup_c_mid["job_titles"]) # senior
        self.assertNotIn("Onsite Architect", startup_c_mid["job_titles"]) # senior
        self.assertIn("Mid Dev", startup_c_mid["job_titles"]) # mid



if __name__ == '__main__':
    unittest.main(verbosity=2)
