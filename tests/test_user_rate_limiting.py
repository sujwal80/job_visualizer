#!/usr/bin/env python3
"""
Test Suite: tests/test_user_rate_limiting.py
Verifies the Configurable Per-User Rate Limiting (R3) requirements:
- Anonymous rate limiting works (keyed by client IP, using RATE_LIMIT_ANON).
- Authenticated rate limiting works and allows higher throughput (keyed by user ID, using RATE_LIMIT_AUTH).
- Exceeding the limits returns 429 status code and Retry-After header.
- Changing limits dynamically (via env or config override) adjusts threshold.
- Crossover: a blocked anonymous IP can login and make successful authenticated requests immediately.
"""

import unittest
import sys
import os
import json
import time
from unittest.mock import patch

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.unified_router import UnifiedRequest, UnifiedRouter
from backend.services.auth_service import reset_auth_stores, issue_jwt_token
from backend.utils.rate_limiter import _rate_limits
from backend import config


class TestUserRateLimiting(unittest.IsolatedAsyncioTestCase):
    """Test suite for per-user rate limiting, environmental overrides, and crossover."""

    def setUp(self):
        self.router = UnifiedRouter()
        # Reset auth services in-memory store
        reset_auth_stores()
        # Clear rate limits dictionary
        _rate_limits.clear()
        # Reset config to defaults
        config.setup_config(None)

    def tearDown(self):
        # Clean up rate limits and configuration
        _rate_limits.clear()
        config.setup_config(None)

    async def test_anonymous_rate_limiting(self):
        # Override config limits for testing
        config.RATE_LIMIT_ANON = 3
        client_ip = "192.168.1.100"

        # First 3 requests should be allowed (404 is allowed by rate limiting, since path is dummy)
        for i in range(3):
            req = UnifiedRequest(
                method="GET",
                path="/api/nonexistent",
                url=f"http://localhost/api/nonexistent",
                client_ip=client_ip
            )
            res = await self.router.handle_request(req)
            self.assertNotEqual(res.status, 429)

        # 4th request must be rate limited (429)
        req = UnifiedRequest(
            method="GET",
            path="/api/nonexistent",
            url=f"http://localhost/api/nonexistent",
            client_ip=client_ip
        )
        res = await self.router.handle_request(req)
        self.assertEqual(res.status, 429)
        self.assertEqual(res.body, {"error": "Rate limit exceeded. Please try again later."})
        self.assertIn("retry-after", res.headers)
        self.assertTrue(int(res.headers["retry-after"]) > 0)

    async def test_authenticated_rate_limiting(self):
        config.RATE_LIMIT_AUTH = 4
        client_ip = "192.168.1.101"
        token = issue_jwt_token({"sub": "user_abc_123", "email": "user@test.com", "name": "Test User"})

        # First 4 requests should be allowed
        for i in range(4):
            req = UnifiedRequest(
                method="GET",
                path="/api/nonexistent",
                url=f"http://localhost/api/nonexistent",
                cookies={"session_token": token},
                client_ip=client_ip
            )
            res = await self.router.handle_request(req)
            self.assertNotEqual(res.status, 429)

        # 5th request must be rate limited
        req = UnifiedRequest(
            method="GET",
            path="/api/nonexistent",
            url=f"http://localhost/api/nonexistent",
            cookies={"session_token": token},
            client_ip=client_ip
        )
        res = await self.router.handle_request(req)
        self.assertEqual(res.status, 429)
        self.assertIn("retry-after", res.headers)

    async def test_env_override_rate_limiting(self):
        # Simulate loading env variables via setup_config
        env_override = {
            "RATE_LIMIT_ANON": "5",
            "RATE_LIMIT_AUTH": "10"
        }
        config.setup_config(env_override)

        self.assertEqual(config.RATE_LIMIT_ANON, 5)
        self.assertEqual(config.RATE_LIMIT_AUTH, 10)

        client_ip = "192.168.1.102"
        # Make 5 successful requests
        for i in range(5):
            req = UnifiedRequest(
                method="GET",
                path="/api/nonexistent",
                url=f"http://localhost/api/nonexistent",
                client_ip=client_ip
            )
            res = await self.router.handle_request(req)
            self.assertNotEqual(res.status, 429)

        # 6th request gets blocked
        req = UnifiedRequest(
            method="GET",
            path="/api/nonexistent",
            url=f"http://localhost/api/nonexistent",
            client_ip=client_ip
        )
        res = await self.router.handle_request(req)
        self.assertEqual(res.status, 429)

    async def test_auth_aware_crossover(self):
        config.RATE_LIMIT_ANON = 2
        config.RATE_LIMIT_AUTH = 4
        client_ip = "192.168.1.103"
        token = issue_jwt_token({"sub": "user_xyz_789", "email": "crossover@test.com", "name": "Crossover User"})

        # 1. Exhaust anonymous rate limit
        for i in range(2):
            req = UnifiedRequest(
                method="GET",
                path="/api/nonexistent",
                url=f"http://localhost/api/nonexistent",
                client_ip=client_ip
            )
            res = await self.router.handle_request(req)
            self.assertNotEqual(res.status, 429)

        # Verify 3rd anonymous request gets blocked
        req_anon_blocked = UnifiedRequest(
            method="GET",
            path="/api/nonexistent",
            url=f"http://localhost/api/nonexistent",
            client_ip=client_ip
        )
        res_anon_blocked = await self.router.handle_request(req_anon_blocked)
        self.assertEqual(res_anon_blocked.status, 429)

        # 2. Login (pass JWT session token) from the SAME IP address.
        # This should immediately succeed and bypass the blocked IP limit because we use the authenticated limit!
        req_auth = UnifiedRequest(
            method="GET",
            path="/api/nonexistent",
            url=f"http://localhost/api/nonexistent",
            cookies={"session_token": token},
            client_ip=client_ip
        )
        res_auth = await self.router.handle_request(req_auth)
        self.assertNotEqual(res_auth.status, 429)  # Should NOT be blocked!

        # We can make 3 more authenticated requests (total 4 allowed)
        for i in range(3):
            req = UnifiedRequest(
                method="GET",
                path="/api/nonexistent",
                url=f"http://localhost/api/nonexistent",
                cookies={"session_token": token},
                client_ip=client_ip
            )
            res = await self.router.handle_request(req)
            self.assertNotEqual(res.status, 429)

        # 5th authenticated request gets blocked
        req_auth_blocked = UnifiedRequest(
            method="GET",
            path="/api/nonexistent",
            url=f"http://localhost/api/nonexistent",
            cookies={"session_token": token},
            client_ip=client_ip
        )
        res_auth_blocked = await self.router.handle_request(req_auth_blocked)
        self.assertEqual(res_auth_blocked.status, 429)


if __name__ == '__main__':
    unittest.main(verbosity=2)
