#!/usr/bin/env python3
"""
Test Suite: tests/test_d1_adversarial.py
Conducts adversarial white-box testing and coverage hardening on the D1 database migration 
and Google OAuth security controls.
"""

import unittest
import sys
import os
import json
import time
import asyncio
from urllib.parse import urlparse, parse_qs

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.app import app
from backend.services import auth_service
from backend import config

class TestD1Adversarial(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()
        auth_service.reset_auth_stores()
        
        # Clear/initialize test tables for local D1 database
        asyncio.run(config.DB.exec("DELETE FROM user_profiles; DELETE FROM bookmarks;"))

        # Issue token for a test user
        self.test_user = {
            "sub": "user_d1_adversarial_123",
            "email": "adversarial@worldtech.map",
            "name": "Adversarial Tester",
            "picture": "https://lh3.googleusercontent.com/mock_adv_pic"
        }
        self.token = auth_service.issue_jwt_token(self.test_user)
        self.client.set_cookie('session_token', self.token)

    # ======================================================================
    # 1. SQL Injection attacks on profile GET/POST and bookmarks endpoints
    # ======================================================================

    def test_sql_injection_profile_get(self):
        """Verify that SQL Injection payloads in JWT user_id (sub) are bound safely and do not dump table or crash."""
        sqli_user = {
            "sub": "attacker' OR '1'='1",
            "email": "attacker@worldtech.map",
            "name": "Attacker",
            "picture": "https://lh3.googleusercontent.com/attacker"
        }
        token = auth_service.issue_jwt_token(sqli_user)
        self.client.set_cookie('session_token', token)

        # GET request should safely insert a profile under the literal ID and return it
        resp = self.client.get('/api/user/profile')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data["id"], "attacker' OR '1'='1")

        # Now query with a different user to verify the SQLi user was created as a literal ID
        # and hasn't merged with other users or exposed other data.
        self.client.set_cookie('session_token', self.token)
        resp2 = self.client.get('/api/user/profile')
        self.assertEqual(resp2.status_code, 200)
        data2 = json.loads(resp2.data)
        self.assertEqual(data2["id"], self.test_user["sub"])

    def test_sql_injection_profile_post(self):
        """Verify that SQL Injection payloads in bio, skills, location, name etc. do not compromise the query."""
        sqli_payload = {
            "name": "Name' OR '1'='1",
            "bio": "Bio'; DROP TABLE user_profiles; --",
            "preferred_location": "Location') UNION SELECT 1,2,3,4,5,6,7,8;--",
            "skills": ["Skill' --", "Another' OR 1=1;--"]
        }
        resp = self.client.post('/api/user/profile', json=sqli_payload)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        
        # Verify the inputs were saved as exact literal strings, not executed as SQL
        self.assertEqual(data["name"], sqli_payload["name"])
        self.assertEqual(data["bio"], sqli_payload["bio"])
        self.assertEqual(data["preferred_location"], sqli_payload["preferred_location"])
        self.assertEqual(data["skills"], sqli_payload["skills"])

        # Retrieve profile again to verify persistence
        resp2 = self.client.get('/api/user/profile')
        self.assertEqual(resp2.status_code, 200)
        data2 = json.loads(resp2.data)
        self.assertEqual(data2["bio"], sqli_payload["bio"])

    def test_sql_injection_bookmarks(self):
        """Verify that SQL Injection in company_id does not compromise bookmarks POST/DELETE endpoints."""
        # 1. POST with SQL Injection payload
        sqli_company_id = "1'; DROP TABLE bookmarks;--"
        resp = self.client.post('/api/user/bookmarks', json={"company_id": sqli_company_id})
        self.assertEqual(resp.status_code, 201)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])
        self.assertEqual(data["bookmark"]["company_id"], sqli_company_id)

        # Retrieve bookmarks to verify it exists
        resp_get = self.client.get('/api/user/bookmarks')
        self.assertEqual(resp_get.status_code, 200)
        data_get = json.loads(resp_get.data)
        self.assertEqual(len(data_get), 1)
        self.assertEqual(data_get[0]["company_id"], sqli_company_id)

        # 2. DELETE with SQL Injection payload
        resp_del = self.client.delete('/api/user/bookmarks', json={"company_id": sqli_company_id})
        self.assertEqual(resp_del.status_code, 200)
        
        # Retrieve bookmarks again (should be empty)
        resp_get2 = self.client.get('/api/user/bookmarks')
        self.assertEqual(resp_get2.status_code, 200)
        self.assertEqual(json.loads(resp_get2.data), [])

    # ======================================================================
    # 2. Tampering with profile immutable fields
    # ======================================================================

    def test_tamper_profile_immutable_fields(self):
        """Verify attempting to change id or email in profile POST is rejected/ignored and stays unchanged."""
        # Initial profile check
        resp_init = self.client.get('/api/user/profile')
        self.assertEqual(resp_init.status_code, 200)
        init_data = json.loads(resp_init.data)
        
        # Tamper payload
        tampered_payload = {
            "id": "hacker_user_id_999",
            "email": "hacked_email@attacker.com",
            "name": "Tampered Name",
            "bio": "Updated bio"
        }
        resp_post = self.client.post('/api/user/profile', json=tampered_payload)
        self.assertEqual(resp_post.status_code, 200)
        post_data = json.loads(resp_post.data)
        
        # ID and email must remain unchanged
        self.assertEqual(post_data["id"], self.test_user["sub"])
        self.assertEqual(post_data["email"], self.test_user["email"])
        self.assertEqual(post_data["name"], "Tampered Name")
        self.assertEqual(post_data["bio"], "Updated bio")

        # Verify in DB again via GET
        resp_get = self.client.get('/api/user/profile')
        data_get = json.loads(resp_get.data)
        self.assertEqual(data_get["id"], self.test_user["sub"])
        self.assertEqual(data_get["email"], self.test_user["email"])

    # ======================================================================
    # 3. Empty, malformed, or extreme inputs
    # ======================================================================

    def test_empty_and_special_char_skills(self):
        """Verify saving empty skills list, skills containing special characters, non-ASCII text."""
        payload = {
            "skills": ["C#", "Rust++", "🚀 Python", "русский", "日本語", "   ", "a"*100]
        }
        resp = self.client.post('/api/user/profile', json=payload)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        # Verify skills list is saved correctly
        self.assertEqual(data["skills"], payload["skills"])

    def test_malformed_json_payloads(self):
        """Verify sending malformed JSON payloads does not crash the server and returns 200/400 gracefully."""
        # 1. Malformed JSON syntax (broken string)
        resp = self.client.post('/api/user/profile', data='{"skills": ["python"', content_type='application/json')
        # Router ignores malformed json syntax, defaults fields, and returns 200 with unchanged profile
        self.assertEqual(resp.status_code, 200)
        
        # 2. Malformed job_preferences or skills types
        bad_types_payload = {
            "skills": "not-a-list-but-a-string",
            "job_preferences": "not-a-dict-but-a-string"
        }
        resp2 = self.client.post('/api/user/profile', json=bad_types_payload)
        self.assertEqual(resp2.status_code, 200)
        data2 = json.loads(resp2.data)
        self.assertEqual(data2["skills"], "not-a-list-but-a-string")
        self.assertEqual(data2["job_preferences"], "not-a-dict-but-a-string")

    def test_extreme_input_lengths(self):
        """Verify sending exceptionally long strings for bio and location doesn't break backend."""
        long_bio = "B" * 10000
        long_location = "L" * 2000
        payload = {
            "bio": long_bio,
            "preferred_location": long_location
        }
        resp = self.client.post('/api/user/profile', json=payload)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data["bio"], long_bio)
        self.assertEqual(data["preferred_location"], long_location)

    # ======================================================================
    # 4. Bookmarks edge cases
    # ======================================================================

    def test_duplicate_bookmarks(self):
        """Verify behavior when bookmarking the same company multiple times."""
        # Add first bookmark
        resp1 = self.client.post('/api/user/bookmarks', json={"company_id": "5"})
        self.assertEqual(resp1.status_code, 201)
        
        # Add duplicate bookmark
        resp2 = self.client.post('/api/user/bookmarks', json={"company_id": "5"})
        self.assertEqual(resp2.status_code, 201)
        
        # Retrieve bookmarks (should not raise DB error; let's check count)
        resp_get = self.client.get('/api/user/bookmarks')
        data_get = json.loads(resp_get.data)
        # Note: If no unique constraint is enforced, this will be 2.
        self.assertTrue(len(data_get) >= 1)

    def test_delete_non_existent_bookmark(self):
        """Verify deleting a bookmark that does not exist returns 200 success without error."""
        resp = self.client.delete('/api/user/bookmarks', json={"company_id": "9999"})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])

    def test_delete_bookmark_malformed_ids(self):
        """Verify deleting bookmarks using empty, negative or malformed company IDs."""
        # 1. Empty company_id should return 400 (Missing parameter)
        resp = self.client.delete('/api/user/bookmarks', json={"company_id": ""})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data)
        self.assertIn("error", data)

        # 2. Negative or non-existent malformed company IDs should run DELETE query cleanly and return 200 success
        bad_ids = [-1, "malformed_id_string_xyz"]
        for bad_id in bad_ids:
            with self.subTest(company_id=bad_id):
                resp = self.client.delete('/api/user/bookmarks', json={"company_id": bad_id})
                self.assertEqual(resp.status_code, 200)
                data = json.loads(resp.data)
                self.assertTrue(data["success"])

    # ======================================================================
    # 5. OAuth & Session token security
    # ======================================================================

    def test_csrf_state_replay_and_tampering(self):
        """Verify CSRF state token reuse (replay attack) and tampering (changing redirect path)."""
        # Get state token
        resp = self.client.get('/api/auth/google')
        self.assertEqual(resp.status_code, 200)
        state_token = json.loads(resp.data)["state"]
        
        if ':' in state_token:
            state_val, redirect_val = state_token.split(':', 1)
        else:
            state_val = state_token
            redirect_val = '/'

        # Set cookie state to allow callback
        self.client.set_cookie('oauth_state', state_val)

        # 1. CSRF State Tampering (pointing redirect to an attacker's domain)
        tampered_state = f"{state_val}:http://attacker.com/steal"
        resp_tampered = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={tampered_state}')
        # Should redirect to fallback '/' instead of http://attacker.com/steal
        self.assertEqual(resp_tampered.status_code, 302)
        self.assertEqual(resp_tampered.headers.get("Location"), "/")

        # 2. CSRF State Replay (reusing the consumed state token)
        # Note: the previous request consumed the state_val in validate_oauth_state
        # Let's perform callback again with same state
        self.client.delete_cookie('oauth_state')
        self.client.set_cookie('oauth_state', state_val)
        resp_replay = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state_token}')
        # Should fail with 400 because state was already consumed
        self.assertEqual(resp_replay.status_code, 400)
        self.assertIn("error", json.loads(resp_replay.data))

    def test_bearer_token_tampering(self):
        """Verify that tampered bearer tokens (header/signature) are rejected on protected endpoints."""
        parts = self.token.split('.')
        self.assertEqual(len(parts), 3)

        # 1. Tamper header
        tampered_header = parts[0] + "extra_chars"
        token1 = f"{tampered_header}.{parts[1]}.{parts[2]}"
        
        # 2. Tamper signature
        sig = parts[2]
        tampered_sig = ('a' if sig[0] != 'a' else 'b') + sig[1:]
        token2 = f"{parts[0]}.{parts[1]}.{tampered_sig}"

        # 3. Token signed with wrong secret key
        wrong_token = auth_service.issue_jwt_token(self.test_user, custom_secret="wrong_secret_123_abc")

        tokens_to_test = [token1, token2, wrong_token]
        for idx, t in enumerate(tokens_to_test, 1):
            with self.subTest(tamper_case=idx):
                self.client.delete_cookie('session_token')
                # Try header first
                resp = self.client.get('/api/user/profile', headers={"Authorization": f"Bearer {t}"})
                self.assertEqual(resp.status_code, 401)

    def test_revoked_and_expired_tokens(self):
        """Verify attempting to access profile using revoked (logout) or expired tokens."""
        # 1. Revoked (logout) token
        self.client.set_cookie('session_token', self.token)
        # Confirm profile is accessible
        self.assertEqual(self.client.get('/api/user/profile').status_code, 200)
        # Logout
        resp_logout = self.client.post('/api/auth/logout')
        self.assertEqual(resp_logout.status_code, 200)
        # Re-attempt access using the same token
        self.client.set_cookie('session_token', self.token)
        resp_after_logout = self.client.get('/api/user/profile')
        self.assertEqual(resp_after_logout.status_code, 401)

        # 2. Expired token
        expired_token = auth_service.issue_jwt_token(self.test_user, expires_in=-10)
        self.client.set_cookie('session_token', expired_token)
        resp_expired = self.client.get('/api/user/profile')
        self.assertEqual(resp_expired.status_code, 401)

if __name__ == "__main__":
    unittest.main()
