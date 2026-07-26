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
import unittest.mock
import sys
import os
import json
import time
from urllib.parse import urlparse, parse_qs

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.app import app
from backend.services import auth_service
import asyncio

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
        """Verify login initiation sets oauth_state cookie with HttpOnly, Secure, SameSite=Lax attributes."""
        from backend import config
        original_env = config.ENVIRONMENT
        config.ENVIRONMENT = "production"
        try:
            resp = self.client.get('/api/auth/google')
            self.assertEqual(resp.status_code, 200)
            set_cookie = resp.headers.get("Set-Cookie", "")
            self.assertIn("oauth_state=", set_cookie)
            self.assertIn("HttpOnly", set_cookie, "oauth_state cookie missing HttpOnly attribute!")
            self.assertIn("Secure", set_cookie, "oauth_state cookie missing Secure attribute!")
            self.assertIn("SameSite=Lax", set_cookie, "oauth_state cookie missing SameSite=Lax attribute!")
        finally:
            config.ENVIRONMENT = original_env

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
        """Verify callback with valid state and authorization code succeeds, redirects to next path, and issues session token."""
        # 1. Test with default next parameter (redirects to /)
        init_resp = self.client.get('/api/auth/google')
        state = json.loads(init_resp.data)["state"]
        resp = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        self.assertEqual(resp.status_code, 302, f"Expected HTTP 302 redirect on valid callback, got {resp.status_code}")
        self.assertEqual(resp.headers.get("Location"), "/")
        self.assertIn("session_token=", resp.headers.get("Set-Cookie", ""))

        # 2. Test with custom next parameter (redirects to /jobs)
        init_resp2 = self.client.get('/api/auth/google?next=/jobs')
        state2 = json.loads(init_resp2.data)["state"]
        resp2 = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state2}')
        self.assertEqual(resp2.status_code, 302, f"Expected HTTP 302 redirect on valid callback, got {resp2.status_code}")
        self.assertEqual(resp2.headers.get("Location"), "/jobs")
        self.assertIn("session_token=", resp2.headers.get("Set-Cookie", ""))

    def test_08_jwt_cookie_security_attributes(self):
        """Verify session_token JWT cookie strictly enforces HttpOnly, Secure, and SameSite=Strict."""
        from backend import config
        original_env = config.ENVIRONMENT
        config.ENVIRONMENT = "production"
        try:
            init_resp = self.client.get('/api/auth/google')
            state = json.loads(init_resp.data)["state"]
            
            resp = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
            self.assertEqual(resp.status_code, 302)
            
            cookies = resp.headers.getlist("Set-Cookie")
            session_cookie = [c for c in cookies if c.startswith("session_token=")]
            self.assertTrue(len(session_cookie) > 0, "session_token cookie not found in Set-Cookie headers!")
            
            sc_val = session_cookie[0]
            self.assertIn("HttpOnly", sc_val, "session_token MUST have HttpOnly attribute to prevent XSS theft!")
            self.assertIn("Secure", sc_val, "session_token MUST have Secure attribute to enforce HTTPS!")
            self.assertIn("SameSite=Strict", sc_val, "session_token MUST have SameSite=Strict attribute to prevent CSRF!")
        finally:
            config.ENVIRONMENT = original_env

    def test_09_jwt_token_creation_and_signature_verification(self):
        """Verify direct JWT token creation and signature verification via auth_service."""
        user_payload = {"sub": "test_user_888", "email": "sec@worldtech.map", "name": "Security Engineer"}
        token = auth_service.issue_jwt_token(user_payload, expires_in=1800)
        self.assertIsInstance(token, str)
        self.assertEqual(len(token.split('.')), 3, "JWT must contain 3 dot-separated segments (header.payload.signature)")
        
        decoded = asyncio.run(auth_service.verify_jwt_token(token))
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
        
        self.assertIsNone(asyncio.run(auth_service.verify_jwt_token(expired_token)), "verify_jwt_token should return None for expired token!")
        
        # Test against protected API endpoint
        self.client.set_cookie('session_token', expired_token)
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
        cb_resp = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        self.assertEqual(cb_resp.status_code, 302)
        
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
        cb_resp = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        self.assertEqual(cb_resp.status_code, 302)
        
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
        self.assertEqual(callback_resp.status_code, 302)
        
        # Parse token from Set-Cookie header
        cookies = callback_resp.headers.getlist("Set-Cookie")
        token = None
        for cookie in cookies:
            if cookie.startswith("session_token="):
                token = cookie.split(";")[0].split("=", 1)[1]
        self.assertIsNotNone(token, "session_token not found in Set-Cookie headers!")
        
        # Confirm token works on protected endpoint
        self.assertEqual(self.client.get('/api/user/profile').status_code, 200)
        
        # Call logout
        self.client.post('/api/auth/logout')
        
        # Attempt replay attack using old token
        self.client.set_cookie('session_token', token)
        replay_resp = self.client.get('/api/user/profile')
        self.assertEqual(replay_resp.status_code, 401, "Revoked token must be rejected with HTTP 401 on protected endpoints!")

    def test_15_protected_endpoint_gating_unauthenticated(self):
        """Verify protected API endpoints return HTTP 401 Unauthenticated when missing session cookie."""
        self.client.delete_cookie('session_token')
        protected_endpoints = ['/api/user/profile', '/api/user/bookmarks', '/api/company/export']
        
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
        cb_resp = self.client.get(f'/api/auth/callback?code=mock_code_admin&state={state}')
        self.assertEqual(cb_resp.status_code, 302)
        
        protected_endpoints = ['/api/user/profile', '/api/user/bookmarks', '/api/company/export']
        for ep in protected_endpoints:
            with self.subTest(endpoint=ep):
                resp = self.client.get(ep)
                self.assertEqual(resp.status_code, 200, f"Expected 200 OK on authenticated call to {ep}, got {resp.status_code}")
                data = json.loads(resp.data)
                if ep == '/api/user/profile':
                    self.assertIn("email", data)
                elif ep == '/api/user/bookmarks':
                    self.assertIsInstance(data, list)
                else:
                    self.assertTrue(data.get("authenticated"))

    def test_17_malformed_and_tampered_jwt_tokens_rejected(self):
        """Verify tampered, malformed, and wrong-secret JWT tokens are rejected cleanly with HTTP 401."""
        init_resp = self.client.get('/api/auth/google')
        state = json.loads(init_resp.data)["state"]
        cb_resp = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        self.assertEqual(cb_resp.status_code, 302)
        
        # Parse token from Set-Cookie header
        cookies = cb_resp.headers.getlist("Set-Cookie")
        valid_token = None
        for cookie in cookies:
            if cookie.startswith("session_token="):
                valid_token = cookie.split(";")[0].split("=", 1)[1]
        self.assertIsNotNone(valid_token, "session_token not found in Set-Cookie headers!")
        
        # 1. Tampered signature (change first character of signature segment)
        parts = valid_token.split('.')
        sig = parts[2]
        tampered_sig = ('a' if sig[0] != 'a' else 'b') + sig[1:]
        tampered_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"
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
                self.client = app.test_client()
                self.client.set_cookie('session_token', tok)
                resp = self.client.get('/api/user/profile')
                self.assertNotEqual(resp.status_code, 500, f"Server crashed with 500 on {name}")
                self.assertEqual(resp.status_code, 401, f"Expected 401 Unauthenticated on {name}, got {resp.status_code}")
                data = json.loads(resp.data)
                self.assertIn("error", data)

    def test_18_bearer_header_authorization_support(self):
        """Verify Authorization: Bearer <token> HTTP header works as an alternative to cookies."""
        init_resp = self.client.get('/api/auth/google')
        state = json.loads(init_resp.data)["state"]
        cb_resp = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        self.assertEqual(cb_resp.status_code, 302)
        
        # Parse token from Set-Cookie header
        cookies = cb_resp.headers.getlist("Set-Cookie")
        token = None
        for cookie in cookies:
            if cookie.startswith("session_token="):
                token = cookie.split(";")[0].split("=", 1)[1]
        self.assertIsNotNone(token, "session_token not found in Set-Cookie headers!")
        
        # Clear cookies to ensure header is being used
        self.client.delete_cookie('session_token')
        
        headers = {"Authorization": f"Bearer {token}"}
        resp_profile = self.client.get('/api/user/profile', headers=headers)
        self.assertEqual(resp_profile.status_code, 200)
        self.assertEqual(json.loads(resp_profile.data)["email"], "ujwal@worldtech.map")
        
        resp_status = self.client.get('/api/auth/status', headers=headers)
        self.assertEqual(resp_status.status_code, 200)
        self.assertTrue(json.loads(resp_status.data)["authenticated"])

    def test_19_csrf_state_one_time_use_enforcement(self):
        """Verify CSRF state parameter is strictly single-use to prevent replay attacks."""
        init_resp = self.client.get('/api/auth/google')
        state = json.loads(init_resp.data)["state"]
        
        # First callback consumption succeeds
        resp1 = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        self.assertEqual(resp1.status_code, 302)
        
        # Clear cookies on test client so it doesn't fall back to cookie matching
        self.client.delete_cookie('oauth_state')
        self.client.delete_cookie('session_token')
        
        # Second callback attempt with SAME state must fail with 400
        resp2 = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        self.assertEqual(resp2.status_code, 400, "CSRF state token must be consumed on first use to prevent replay!")

    def test_20_open_redirect_protection_in_auth_google(self):
        """Verify that /api/auth/google rejects unsafe redirect URL and defaults to /."""
        # Unsafe redirect targeting external domain
        resp = self.client.get('/api/auth/google?next=http://attacker.com')
        self.assertEqual(resp.status_code, 200) # Returns JSON with auth_url
        data = json.loads(resp.data)
        self.assertIn("auth_url", data)
        # Verify the state parameter is constructed with / instead of http://attacker.com
        state = data["state"]
        self.assertTrue(state.endswith(":/"), f"Expected state to end with relative fallback :/ but got {state}")

    def test_21_open_redirect_protection_in_callback(self):
        """Verify that /api/auth/callback sanitizes next target and prevents Open Redirects."""
        # Setup valid state with malicious target
        state_token = "legit_token"
        
        from backend import config
        from backend.services.auth_service import _csrf_state_store
        import asyncio
        
        session_store = getattr(config, 'SESSION_STORE', None)
        if session_store:
            asyncio.run(session_store.put(f"csrf:{state_token}", "1", expirationTtl=600))
        else:
            _csrf_state_store[state_token] = time.time() + 600
        
        # Inject cookie state into client
        self.client.set_cookie('oauth_state', state_token)
        
        # Call callback with state parameter pointing to malicious external site
        combined_state = f"{state_token}:http://attacker.com"
        resp = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={combined_state}')
        self.assertEqual(resp.status_code, 302)
        # Location header MUST fallback to relative '/' to prevent Open Redirect
        self.assertEqual(resp.headers.get("Location"), "/")

    def test_22_demo_login_disabled_in_production(self):
        """Verify /api/auth/demo_login is disabled when ENVIRONMENT is production."""
        # Set environment to production
        from backend import config
        original_env = config.ENVIRONMENT
        config.ENVIRONMENT = "production"
        
        try:
            resp = self.client.post('/api/auth/demo_login')
            self.assertEqual(resp.status_code, 403, "Demo login backdoor must be disabled in production!")
            
            resp2 = self.client.get('/api/auth/demo_login')
            self.assertEqual(resp2.status_code, 403)
        finally:
            config.ENVIRONMENT = original_env

    @unittest.mock.patch('backend.services.auth_service.fetch_json', new_callable=unittest.mock.AsyncMock)
    def test_23_real_google_oauth_exchange_success(self, mock_fetch):
        """Verify successful exchange of Google OAuth authorization code for user profile."""
        from backend import config
        mock_fetch.side_effect = [
            {"access_token": "fake_access_token_123"},
            {
                "sub": "google_999",
                "email": "test_user@gmail.com",
                "name": "Test Google User",
                "picture": "https://picture.url"
            }
        ]
        
        user = asyncio.run(auth_service.exchange_code_for_user("real_code_google_999"))
        
        self.assertEqual(user["sub"], "google_999")
        self.assertEqual(user["email"], "test_user@gmail.com")
        self.assertEqual(user["name"], "Test Google User")
        self.assertEqual(user["picture"], "https://picture.url")
        
        self.assertEqual(mock_fetch.call_count, 2)
        
        # Verify first call (token request)
        first_call_args, first_call_kwargs = mock_fetch.call_args_list[0]
        self.assertEqual(first_call_args[0], "https://oauth2.googleapis.com/token")
        self.assertEqual(first_call_kwargs.get("method"), "POST")
        self.assertEqual(first_call_kwargs.get("headers"), {"Content-Type": "application/x-www-form-urlencoded"})
        
        # Parse body form parameters
        body_params = parse_qs(first_call_kwargs.get("body"))
        self.assertEqual(body_params.get("code"), ["real_code_google_999"])
        self.assertEqual(body_params.get("client_id"), [config.GOOGLE_CLIENT_ID])
        self.assertEqual(body_params.get("client_secret"), [config.GOOGLE_CLIENT_SECRET])
        self.assertEqual(body_params.get("grant_type"), ["authorization_code"])
        
        # Verify second call (userinfo request)
        second_call_args, second_call_kwargs = mock_fetch.call_args_list[1]
        self.assertEqual(second_call_args[0], "https://www.googleapis.com/oauth2/v3/userinfo")
        self.assertEqual(second_call_kwargs.get("method"), "GET")
        self.assertEqual(second_call_kwargs.get("headers"), {"Authorization": "Bearer fake_access_token_123"})

    @unittest.mock.patch('backend.services.auth_service.fetch_json', new_callable=unittest.mock.AsyncMock)
    def test_24_real_google_oauth_exchange_token_failure(self, mock_fetch):
        """Verify handling of OAuth token exchange failure."""
        mock_fetch.return_value = {"error": "invalid_grant", "error_description": "Bad code"}
        
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(auth_service.exchange_code_for_user("real_code_google_999"))
            
        self.assertEqual(str(ctx.exception), "Failed to exchange authorization code: Bad code")

    @unittest.mock.patch('backend.services.auth_service.fetch_json', new_callable=unittest.mock.AsyncMock)
    def test_25_real_google_oauth_exchange_userinfo_failure(self, mock_fetch):
        """Verify handling of OAuth user profile retrieval failure."""
        mock_fetch.side_effect = [
            {"access_token": "fake_access_token_123"},
            {"error": "invalid_token", "error_description": "Token expired"}
        ]
        
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(auth_service.exchange_code_for_user("real_code_google_999"))
            
        self.assertEqual(str(ctx.exception), "Failed to retrieve user profile: Token expired")

if __name__ == '__main__':
    print("\n======================================================================")
    print(" 🔒 EXHAUSTIVE GOOGLE OAUTH & SESSION SECURITY VERIFICATION HARNESS 🔒")
    print("======================================================================")
    unittest.main(verbosity=2)
