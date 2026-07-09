#!/usr/bin/env python3
"""
Test Suite: tests/test_oauth_security.py
Verifies Requirement R1: Google OAuth & Session Security Verification.
Tests OAuth login initiation (/api/auth/google), callback CSRF state validation,
stateless JWT token issuance with HttpOnly, Secure, SameSite=Strict cookies,
status checking (/api/auth/status), session logout revocation (/api/auth/logout),
and HTTP 401 unauthenticated gating on protected API endpoints.
"""

import unittest
import sys
import os
import json
import time
from urllib.parse import urlparse, parse_qs

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.app import app
from backend.services import auth_service

class TestOAuthAndSessionSecurity(unittest.TestCase):
    """Exhaustive automated verification harness for Google OAuth & Session Security."""
    
    def setUp(self):
        app.testing = True
        self.client = app.test_client()
        auth_service.reset_auth_stores()

    def test_01_login_initiation_json_format(self):
        """Verify GET /api/auth/google returns 200 OK with valid Google OAuth authorization URL and CSRF state."""
        resp = self.client.get('/api/auth/google')
        self.assertEqual(resp.status_code, 200, "Expected HTTP 200 on login initiation.")
        data = json.loads(resp.data)
        self.assertIn("auth_url", data)
        self.assertIn("state", data)
        
        auth_url = data["auth_url"]
        self.assertTrue(auth_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?"), f"Invalid OAuth host/path: {auth_url}")
        
        parsed = urlparse(auth_url)
        params = parse_qs(parsed.query)
        self.assertEqual(params.get("response_type"), ["code"])
        self.assertEqual(params.get("scope"), ["openid email profile"])
        self.assertEqual(params.get("state"), [data["state"]])
        self.assertEqual(params.get("access_type"), ["offline"])
        self.assertEqual(params.get("prompt"), ["consent"])
        self.assertIn("client_id", params)
        self.assertIn("redirect_uri", params)

    def test_02_login_initiation_302_redirect(self):
        """Verify GET /api/auth/google?redirect=true performs an HTTP 302 redirect to Google OAuth."""
        resp = self.client.get('/api/auth/google?redirect=true')
        self.assertEqual(resp.status_code, 302, "Expected HTTP 302 redirect when redirect=true is requested.")
        location = resp.headers.get("Location", "")
        self.assertTrue(location.startswith("https://accounts.google.com/o/oauth2/v2/auth?"))

    def test_03_login_initiation_sets_oauth_state_cookie(self):
        """Verify login initiation sets oauth_state cookie with HttpOnly, Secure, SameSite=Strict attributes."""
        resp = self.client.get('/api/auth/google')
        self.assertEqual(resp.status_code, 200)
        set_cookie = resp.headers.get("Set-Cookie", "")
        self.assertIn("oauth_state=", set_cookie)
        self.assertIn("HttpOnly", set_cookie, "oauth_state cookie missing HttpOnly attribute!")
        self.assertIn("Secure", set_cookie, "oauth_state cookie missing Secure attribute!")
        self.assertIn("SameSite=Strict", set_cookie, "oauth_state cookie missing SameSite=Strict attribute!")

    def test_04_callback_missing_state_returns_400(self):
        """Verify callback without CSRF state parameter is rejected with HTTP 400."""
        resp = self.client.get('/api/auth/callback?code=mock_code_user1')
        self.assertEqual(resp.status_code, 400, "Expected HTTP 400 when CSRF state parameter is missing.")
        data = json.loads(resp.data)
        self.assertIn("error", data)

    def test_05_callback_invalid_state_returns_400(self):
        """Verify callback with invalid/tampered CSRF state parameter is rejected with HTTP 400."""
        resp = self.client.get('/api/auth/callback?code=mock_code_user1&state=invalid_attacker_state_token_9999')
        self.assertEqual(resp.status_code, 400, "Expected HTTP 400 when CSRF state parameter is invalid/tampered.")
        data = json.loads(resp.data)
        self.assertIn("error", data)

    def test_06_callback_missing_code_returns_400(self):
        """Verify callback with valid state but missing authorization code is rejected with HTTP 400."""
        init_resp = self.client.get('/api/auth/google')
        state = json.loads(init_resp.data)["state"]
        
        resp = self.client.get(f'/api/auth/callback?state={state}')
        self.assertEqual(resp.status_code, 400, "Expected HTTP 400 when OAuth authorization code is missing.")
        data = json.loads(resp.data)
        self.assertIn("error", data)

    def test_07_callback_valid_state_and_code_success(self):
        """Verify callback with valid state and authorization code succeeds and issues session token."""
        init_resp = self.client.get('/api/auth/google')
        state = json.loads(init_resp.data)["state"]
        
        resp = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        self.assertEqual(resp.status_code, 200, f"Expected HTTP 200 on valid callback, got {resp.status_code}")
        data = json.loads(resp.data)
        self.assertTrue(data.get("authenticated"))
        self.assertEqual(data["user"]["email"], "ujwal@worldtech.map")
        self.assertIn("token", data)
        self.assertIn("session_token=", resp.headers.get("Set-Cookie", ""))

    def test_08_jwt_cookie_security_attributes(self):
        """Verify session_token JWT cookie strictly enforces HttpOnly, Secure, and SameSite=Strict."""
        init_resp = self.client.get('/api/auth/google')
        state = json.loads(init_resp.data)["state"]
        
        resp = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        self.assertEqual(resp.status_code, 200)
        
        cookies = resp.headers.getlist("Set-Cookie")
        session_cookie = [c for c in cookies if c.startswith("session_token=")]
        self.assertTrue(len(session_cookie) > 0, "session_token cookie not found in Set-Cookie headers!")
        
        sc_val = session_cookie[0]
        self.assertIn("HttpOnly", sc_val, "session_token MUST have HttpOnly attribute to prevent XSS theft!")
        self.assertIn("Secure", sc_val, "session_token MUST have Secure attribute to enforce HTTPS!")
        self.assertIn("SameSite=Strict", sc_val, "session_token MUST have SameSite=Strict attribute to prevent CSRF!")

    def test_09_jwt_token_creation_and_signature_verification(self):
        """Verify direct JWT token creation and signature verification via auth_service."""
        user_payload = {"sub": "test_user_888", "email": "sec@worldtech.map", "name": "Security Engineer"}
        token = auth_service.issue_jwt_token(user_payload, expires_in=1800)
        self.assertIsInstance(token, str)
        self.assertEqual(len(token.split('.')), 3, "JWT must contain 3 dot-separated segments (header.payload.signature)")
        
        decoded = auth_service.verify_jwt_token(token)
        self.assertIsNotNone(decoded, "verify_jwt_token failed on valid token!")
        self.assertEqual(decoded["sub"], "test_user_888")
        self.assertEqual(decoded["email"], "sec@worldtech.map")
        self.assertIn("iat", decoded)
        self.assertIn("exp", decoded)
        self.assertIn("jti", decoded)

    def test_10_jwt_token_expiration_handling(self):
        """Verify expired JWT tokens are rejected by verification logic and protected endpoints."""
        user_payload = {"sub": "expired_user", "email": "old@worldtech.map"}
        expired_token = auth_service.issue_jwt_token(user_payload, expires_in=-10) # 10 seconds in the past
        
        self.assertIsNone(auth_service.verify_jwt_token(expired_token), "verify_jwt_token should return None for expired token!")
        
        # Test against protected API endpoint
        self.client.set_cookie('session_token', expired_token, domain='localhost')
        resp = self.client.get('/api/user/profile')
        self.assertEqual(resp.status_code, 401, f"Expected 401 on expired token, got {resp.status_code}")
        data = json.loads(resp.data)
        self.assertIn("error", data)

    def test_11_auth_status_unauthenticated(self):
        """Verify /api/auth/status returns authenticated=false when no session cookie is present."""
        resp = self.client.get('/api/auth/status')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertFalse(data.get("authenticated"))
        self.assertIsNone(data.get("user"))

    def test_12_auth_status_authenticated(self):
        """Verify /api/auth/status returns authenticated=true and user profile when valid session cookie is present."""
        init_resp = self.client.get('/api/auth/google')
        state = json.loads(init_resp.data)["state"]
        self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        
        resp = self.client.get('/api/auth/status')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("authenticated"))
        self.assertEqual(data["user"]["email"], "ujwal@worldtech.map")
        self.assertIn("id", data["user"])
        self.assertIn("name", data["user"])

    def test_13_logout_clears_cookies_and_revokes_session(self):
        """Verify /api/auth/logout clears session cookies and subsequent status check returns unauthenticated."""
        init_resp = self.client.get('/api/auth/google')
        state = json.loads(init_resp.data)["state"]
        self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        
        # Verify authenticated first
        self.assertTrue(json.loads(self.client.get('/api/auth/status').data)["authenticated"])
        
        # Call logout
        logout_resp = self.client.post('/api/auth/logout')
        self.assertEqual(logout_resp.status_code, 200)
        self.assertFalse(json.loads(logout_resp.data)["authenticated"])
        
        cookies = logout_resp.headers.getlist("Set-Cookie")
        session_cookie = [c for c in cookies if c.startswith("session_token=")]
        self.assertTrue(len(session_cookie) > 0)
        # Check cookie cleared (Expires in past or empty value)
        self.assertTrue("Expires=" in session_cookie[0] or "max-age=0" in session_cookie[0].lower() or "session_token=;" in session_cookie[0])
        
        # Status check must now be unauthenticated
        self.assertFalse(json.loads(self.client.get('/api/auth/status').data)["authenticated"])

    def test_14_logout_revoked_token_rejected_on_protected_endpoint(self):
        """Verify that a revoked JWT token cannot be reused on protected API endpoints after logout."""
        init_resp = self.client.get('/api/auth/google')
        state = json.loads(init_resp.data)["state"]
        callback_resp = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        token = json.loads(callback_resp.data)["token"]
        
        # Confirm token works on protected endpoint
        self.assertEqual(self.client.get('/api/user/profile').status_code, 200)
        
        # Call logout
        self.client.post('/api/auth/logout')
        
        # Attempt replay attack using old token
        self.client.set_cookie('session_token', token, domain='localhost')
        replay_resp = self.client.get('/api/user/profile')
        self.assertEqual(replay_resp.status_code, 401, "Revoked token must be rejected with HTTP 401 on protected endpoints!")

    def test_15_protected_endpoint_gating_unauthenticated(self):
        """Verify protected API endpoints return HTTP 401 Unauthenticated when missing session cookie."""
        self.client.delete_cookie('session_token')
        protected_endpoints = ['/api/user/profile', '/api/user/bookmarks', '/api/startups/export']
        
        for ep in protected_endpoints:
            with self.subTest(endpoint=ep):
                resp = self.client.get(ep)
                self.assertEqual(resp.status_code, 401, f"Expected 401 Unauthenticated on {ep}, got {resp.status_code}")
                data = json.loads(resp.data)
                self.assertIn("error", data)

    def test_16_protected_endpoint_gating_authenticated(self):
        """Verify protected API endpoints return HTTP 200 OK when authenticated with valid session cookie."""
        init_resp = self.client.get('/api/auth/google')
        state = json.loads(init_resp.data)["state"]
        self.client.get(f'/api/auth/callback?code=mock_code_admin&state={state}')
        
        protected_endpoints = ['/api/user/profile', '/api/user/bookmarks', '/api/startups/export']
        for ep in protected_endpoints:
            with self.subTest(endpoint=ep):
                resp = self.client.get(ep)
                self.assertEqual(resp.status_code, 200, f"Expected 200 OK on authenticated call to {ep}, got {resp.status_code}")
                data = json.loads(resp.data)
                self.assertTrue(data.get("authenticated"))

    def test_17_malformed_and_tampered_jwt_tokens_rejected(self):
        """Verify tampered, malformed, and wrong-secret JWT tokens are rejected cleanly with HTTP 401."""
        init_resp = self.client.get('/api/auth/google')
        state = json.loads(init_resp.data)["state"]
        cb_data = json.loads(self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}').data)
        valid_token = cb_data["token"]
        
        # 1. Tampered signature (change last character)
        tampered_token = valid_token[:-1] + ('a' if valid_token[-1] != 'a' else 'b')
        # 2. Completely malformed token
        malformed_token = "invalid.jwt.token.string"
        # 3. Token signed with attacker secret key
        attacker_token = auth_service.issue_jwt_token({"sub": "attacker"}, custom_secret="attacker_super_secret_key")
        
        test_cases = [
            ("Tampered signature", tampered_token),
            ("Malformed string", malformed_token),
            ("Wrong secret key", attacker_token)
        ]
        
        for name, tok in test_cases:
            with self.subTest(token_type=name):
                self.client.delete_cookie('session_token', domain='localhost')
                self.client.set_cookie('session_token', tok, domain='localhost')
                resp = self.client.get('/api/user/profile')
                self.assertNotEqual(resp.status_code, 500, f"Server crashed with 500 on {name}")
                self.assertEqual(resp.status_code, 401, f"Expected 401 Unauthenticated on {name}, got {resp.status_code}")
                data = json.loads(resp.data)
                self.assertIn("error", data)

    def test_18_bearer_header_authorization_support(self):
        """Verify Authorization: Bearer <token> HTTP header works as an alternative to cookies."""
        init_resp = self.client.get('/api/auth/google')
        state = json.loads(init_resp.data)["state"]
        cb_data = json.loads(self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}').data)
        token = cb_data["token"]
        
        # Clear cookies to ensure header is being used
        self.client.delete_cookie('session_token')
        
        headers = {"Authorization": f"Bearer {token}"}
        resp_profile = self.client.get('/api/user/profile', headers=headers)
        self.assertEqual(resp_profile.status_code, 200)
        self.assertEqual(json.loads(resp_profile.data)["user"]["email"], "ujwal@worldtech.map")
        
        resp_status = self.client.get('/api/auth/status', headers=headers)
        self.assertEqual(resp_status.status_code, 200)
        self.assertTrue(json.loads(resp_status.data)["authenticated"])

    def test_19_csrf_state_one_time_use_enforcement(self):
        """Verify CSRF state parameter is strictly single-use to prevent replay attacks."""
        init_resp = self.client.get('/api/auth/google')
        state = json.loads(init_resp.data)["state"]
        
        # First callback consumption succeeds
        resp1 = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        self.assertEqual(resp1.status_code, 200)
        
        # Clear cookies on test client so it doesn't fall back to cookie matching
        self.client.delete_cookie('oauth_state')
        self.client.delete_cookie('session_token')
        
        # Second callback attempt with SAME state must fail with 400
        resp2 = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        self.assertEqual(resp2.status_code, 400, "CSRF state token must be consumed on first use to prevent replay!")

if __name__ == '__main__':
    print("\n======================================================================")
    print(" 🔒 EXHAUSTIVE GOOGLE OAUTH & SESSION SECURITY VERIFICATION HARNESS 🔒")
    print("======================================================================")
    unittest.main(verbosity=2)
