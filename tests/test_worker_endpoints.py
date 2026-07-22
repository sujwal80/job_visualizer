#!/usr/bin/env python3
"""
Test Suite: tests/test_worker_endpoints.py
Verifies Cloudflare Workers entrypoint implementation.
"""

import unittest
import sys
import os
import json
import asyncio
import time
from urllib.parse import urlparse, parse_qs

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.worker import WorkerEntrypoint, Request, Headers, Response
from backend.services import auth_service
from backend.utils.rate_limiter import _rate_limits

MOCK_STARTUPS = [
    {
        "id": "st-1.json",
        "name": "Acme Corp",
        "city": "Bengaluru",
        "lat": 12.9716,
        "lng": 77.5946,
        "industry": "Service Industry",
        "description": "Acme Corporation",
        "funding_stage": "Seed",
        "total_raised": "1M",
        "verified_email": "contact@acme.com",
        "founders": [{"name": "John Doe", "linkedin": "https://linkedin.com/johndoe"}],
        "job_openings": [
            {
                "title": "Software Engineer",
                "department": "Engineering",
                "experience": "2+ years",
                "salary": "15-20 LPA",
                "job_type": "Full-Time",
                "location": "Bengaluru",
                "posted_date": "2026-07-01",
                "source": "LinkedIn",
                "url": "https://linkedin.com/jobs/acme",
                "skills": ["Python", "Flask"]
            }
        ]
    },
    {
        "id": "st-2.json",
        "name": "Beta Startup",
        "city": "Mumbai",
        "lat": 19.0760,
        "lng": 72.8777,
        "industry": "Software",
        "description": "Beta Startup Description",
        "funding_stage": "Pre-seed",
        "total_raised": "100k",
        "verified_email": "contact@beta.io"
    }
]

class MockKVStore:
    def __init__(self):
        self.store = {}
        self.expirations = {}

    async def put(self, key, value, expirationTtl=None):
        self.store[key] = str(value)
        if expirationTtl is not None:
            self.expirations[key] = time.time() + expirationTtl

    async def get(self, key):
        if key in self.expirations and time.time() > self.expirations[key]:
            self.store.pop(key, None)
            self.expirations.pop(key, None)
            return None
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)
        self.expirations.pop(key, None)

class MockAssetsBinding:
    def __init__(self, data):
        self.assets = {
            "/index.html": ("<html>Index</html>", "text/html"),
            "/static/data/startups.json": (json.dumps(data), "application/json")
        }

    async def fetch(self, request):
        url_str = request.url if isinstance(request.url, str) else str(request.url)
        parsed = urlparse(url_str)
        path = parsed.path
        
        class MockResponse:
            def __init__(self, body, status=200, content_type="text/plain"):
                self.body = body
                self.status = status
                self.headers = Headers()
                self.headers.set("Content-Type", content_type)
            async def json(self):
                if isinstance(self.body, str):
                    try:
                        return json.loads(self.body)
                    except Exception:
                        pass
                return self.body
            async def text(self):
                if not isinstance(self.body, str):
                    return json.dumps(self.body)
                return self.body

        if path in self.assets:
            content, content_type = self.assets[path]
            return MockResponse(content, status=200, content_type=content_type)
        else:
            return MockResponse("Not Found", status=404)

class MockEnv:
    def __init__(self):
        self.SESSION_STORE = MockKVStore()
        self.ASSETS = MockAssetsBinding(MOCK_STARTUPS)
        self.DEFAULT_TARGET_CITY = "Bengaluru"
        self.DEFAULT_MAP_CENTER_LAT = "12.9716"
        self.DEFAULT_MAP_CENTER_LNG = "77.5946"
        self.RATE_LIMIT_ANON = "120"
        self.RATE_LIMIT_AUTH = "200"

class TestWorkerEndpoints(unittest.TestCase):
    def setUp(self):
        self.env = MockEnv()
        self.worker = WorkerEntrypoint(self.env)
        _rate_limits.clear()
        auth_service.reset_auth_stores()

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_options_preflight(self):
        """Verify OPTIONS preflight request handling."""
        req = Request("http://localhost/api/companies", method="OPTIONS")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 204)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "*")
        self.assertEqual(resp.headers.get("access-control-allow-methods"), "GET, POST, DELETE, OPTIONS")

    def test_assets_forwarding(self):
        """Verify non-API requests are routed to ASSETS, rewritten if page route, and security headers are attached."""
        # 1. Requesting /map (should be intercepted, rewritten to /index.html, and return 200 with HTML)
        req = Request("http://localhost/map", method="GET")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, "<html>Index</html>")
        self.assertIsNotNone(resp.headers.get("content-security-policy"))
        self.assertEqual(resp.headers.get("x-content-type-options"), "nosniff")

        # 2. Requesting /jobs (should be intercepted, rewritten to /index.html, and return 200 with HTML)
        req = Request("http://localhost/jobs", method="GET")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, "<html>Index</html>")

        # 3. Requesting / (should be intercepted, rewritten to /index.html, and return 200 with HTML)
        req = Request("http://localhost/", method="GET")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, "<html>Index</html>")

        # 4. Requesting /static/data/startups.json (should return 200 with startup JSON data)
        req = Request("http://localhost/static/data/startups.json", method="GET")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 200)
        # Verify JSON content
        data = json.loads(resp.body)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["name"], "Acme Corp")

        # 5. Requesting /nonexistent-file.txt (should return 404)
        req = Request("http://localhost/nonexistent-file.txt", method="GET")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 404)

    def test_rate_limiting(self):
        """Verify rate limiting returns 429 after threshold is crossed."""
        req = Request("http://localhost/api/companies", method="GET", headers={"CF-Connecting-IP": "10.0.0.1"})
        
        # We need to trigger rate limits by invoking _check_rate_limit inside worker.
        # Limit is 120, let's verify we can trigger 429 if we lower limit or just call it 121 times.
        # But wait! In python rate_limiter, we can mock _rate_limits or just set window or limit.
        # Let's call it 120 times, then 121st should fail.
        for i in range(120):
            resp = self.run_async(self.worker.fetch(req))
            self.assertEqual(resp.status, 200)
            
        # 121st request
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 429)
        self.assertEqual(json.loads(resp.body)["error"], "Rate limit exceeded. Please try again later.")
        self.assertIsNotNone(resp.headers.get("retry-after"))

    def test_get_companies(self):
        """Verify GET /api/companies returns matching records."""
        req = Request("http://localhost/api/companies?city=bengaluru", method="GET")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 200)
        
        data = json.loads(resp.body)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "Acme Corp")
        self.assertIsNotNone(resp.headers.get("x-data-version"))

    def test_get_companies_filter_jobs(self):
        """Verify has_jobs=true filtering and format_lightweight_summary."""
        req = Request("http://localhost/api/companies?has_jobs=true", method="GET")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 200)
        
        data = json.loads(resp.body)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "Acme Corp")
        # Lightweight summary format shouldn't have detailed founders list etc.
        self.assertNotIn("founders", data[0])

    def test_get_company_by_id(self):
        """Verify GET /api/companies/<id> returns detail payload."""
        req = Request("http://localhost/api/companies/st-1.json", method="GET")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 200)
        
        data = json.loads(resp.body)
        self.assertEqual(data["name"], "Acme Corp")
        self.assertEqual(len(data["jobs"]), 1)

    def test_get_company_by_id_not_found(self):
        """Verify GET /api/companies/<id> returns 404 for missing records."""
        req = Request("http://localhost/api/companies/missing.json", method="GET")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 404)
        self.assertEqual(json.loads(resp.body)["error"], "Startup not found")

    def test_auth_google_api(self):
        """Verify GET /api/auth/google generates state and returns JSON flow."""
        req = Request("http://localhost/api/auth/google", method="GET")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 200)
        
        data = json.loads(resp.body)
        self.assertIn("auth_url", data)
        self.assertIn("state", data)
        
        # Verify state is stored in KV
        state = data["state"]
        state_token = state.split(':', 1)[0] if ':' in state else state
        stored_state = self.run_async(self.env.SESSION_STORE.get(f"csrf:{state_token}"))
        self.assertEqual(stored_state, "1")

    def test_auth_google_redirect(self):
        """Verify GET /api/auth/google?redirect=true returns 302 redirect."""
        req = Request("http://localhost/api/auth/google?redirect=true", method="GET")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 302)
        
        loc = resp.headers.get("location")
        self.assertTrue(loc.startswith("https://accounts.google.com/o/oauth2/v2/auth"))
        
        # Verify cookie was set
        cookies = [v for k, v in resp.headers.entries() if k == "set-cookie"]
        self.assertTrue(any("oauth_state=" in c for c in cookies))

    def test_auth_callback_success(self):
        """Verify OAuth callback state validation and JWT cookie emission."""
        # 1. Setup CSRF state
        state_token = "test_csrf_state"
        combined_state = f"{state_token}:/jobs"
        self.run_async(self.env.SESSION_STORE.put(f"csrf:{state_token}", "1", expirationTtl=300))
        
        # 2. Call callback with matching cookie state
        headers = Headers.new()
        headers.set("Cookie", f"oauth_state={state_token}")
        req = Request(
            f"http://localhost/api/auth/callback?code=mock_code_user1&state={combined_state}",
            {"headers": headers, "method": "GET"}
        )
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.headers.get("location"), "/jobs")
        
        # Verify session_token cookie set
        cookies = [v for k, v in resp.headers.entries() if k == "set-cookie"]
        self.assertTrue(any("session_token=" in c for c in cookies))
        
        # Verify state consumed
        stored_state = self.run_async(self.env.SESSION_STORE.get(f"csrf:{state_token}"))
        self.assertIsNone(stored_state)

    def test_auth_demo_login(self):
        """Verify demo login flow."""
        req = Request("http://localhost/api/auth/demo_login", method="POST")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 200)
        
        data = json.loads(resp.body)
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["user"]["email"], "ujwal@worldtech.map")

    def test_auth_status_flow(self):
        """Verify authentication status endpoint checks cookie or Authorization header."""
        # 1. Start unauthenticated
        req = Request("http://localhost/api/auth/status", method="GET")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 200)
        self.assertFalse(json.loads(resp.body)["authenticated"])

        # 2. Issue a token and pass it via Authorization Bearer header
        user_payload = {"sub": "usr_123", "email": "user@test.io", "name": "Test User"}
        token = auth_service.issue_jwt_token(user_payload)
        
        req_auth = Request("http://localhost/api/auth/status", method="GET", headers={"Authorization": f"Bearer {token}"})
        resp_auth = self.run_async(self.worker.fetch(req_auth))
        self.assertEqual(resp_auth.status, 200)
        
        data = json.loads(resp_auth.body)
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["user"]["email"], "user@test.io")

    def test_auth_logout(self):
        """Verify logout revokes token and clears session cookie."""
        user_payload = {"sub": "usr_logout", "email": "logout@test.io", "name": "Logout User"}
        token = auth_service.issue_jwt_token(user_payload)
        
        req = Request("http://localhost/api/auth/logout", method="POST", headers={"Cookie": f"session_token={token}"})
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 200)
        
        # Verify cookies cleared
        cookies = [v for k, v in resp.headers.entries() if k == "set-cookie"]
        self.assertTrue(any("session_token=;" in c for c in cookies))

        # Verify token is revoked in KV
        jti = self.run_async(auth_service.verify_jwt_token(token)) # Decode token claims to get jti
        self.assertIsNotNone(jti)
        revoked_val = self.run_async(self.env.SESSION_STORE.get(f"revoked:{jti['jti']}"))
        self.assertEqual(revoked_val, "1")

    def test_protected_endpoints_unauthenticated(self):
        """Verify protected endpoints return 401 if unauthenticated."""
        req = Request("http://localhost/api/user/profile", method="GET")
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 401)
        error_msg = json.loads(resp.body)["error"]
        self.assertTrue(
            error_msg in (
                "Unauthenticated. Missing or invalid JWT session token.",
                "Unauthenticated. Missing JWT session token."
            ),
            f"Unexpected error message: {error_msg}"
        )


    def test_protected_endpoints_authenticated(self):
        """Verify protected endpoints return 200 if authenticated."""
        user_payload = {"sub": "usr_profile", "email": "profile@test.io", "name": "Profile User"}
        token = auth_service.issue_jwt_token(user_payload)
        
        req = Request("http://localhost/api/user/profile", method="GET", headers={"Authorization": f"Bearer {token}"})
        resp = self.run_async(self.worker.fetch(req))
        self.assertEqual(resp.status, 200)
        
        data = json.loads(resp.body)
        self.assertEqual(data["email"], "profile@test.io")

if __name__ == '__main__':
    unittest.main(verbosity=2)
