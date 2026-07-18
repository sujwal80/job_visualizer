#!/usr/bin/env python3
"""
Test Suite: tests/test_oauth_kv.py
Verifies Requirement: Cloudflare KV session store integration.
Tests async state generation, validation, and token revocation with a mocked KV store.
"""

import unittest
import sys
import os
import json
import time
import asyncio
from urllib.parse import urlparse, parse_qs

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.app import app
from backend import config
from backend.services import auth_service

class MockKVStore:
    """Mock Cloudflare KV Namespace supporting async put, get, and delete."""
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

class TestOAuthKVIntegration(unittest.TestCase):
    """Verifies Cloudflare KV session store integration and API behavior."""

    def setUp(self):
        app.testing = True
        self.client = app.test_client()
        self.mock_kv = MockKVStore()
        # Mock global config if needed, or we can use environ overrides.
        self._old_session_store = getattr(config, 'SESSION_STORE', None)
        config.SESSION_STORE = self.mock_kv
        auth_service.reset_auth_stores()

    def tearDown(self):
        if self._old_session_store is not None:
            config.SESSION_STORE = self._old_session_store
        else:
            if hasattr(config, 'SESSION_STORE'):
                delattr(config, 'SESSION_STORE')

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_kv_direct_state_generation(self):
        """Verify generate_oauth_state stores CSRF state in KV with correct TTL."""
        state = self.run_async(auth_service.generate_oauth_state(expires_in=300, session_store=self.mock_kv))
        self.assertIsNotNone(state)
        
        # Verify it was put into the KV store
        stored_val = self.run_async(self.mock_kv.get(f"csrf:{state}"))
        self.assertEqual(stored_val, "1")
        
        # Verify expiration was set
        expiration = self.mock_kv.expirations.get(f"csrf:{state}")
        self.assertIsNotNone(expiration)
        self.assertTrue(expiration > time.time())

    def test_kv_direct_state_validation_success(self):
        """Verify validate_oauth_state validates and consumes (deletes) the state from KV."""
        state = self.run_async(auth_service.generate_oauth_state(expires_in=300, session_store=self.mock_kv))
        
        # Validate state (should return True and delete from KV)
        is_valid = self.run_async(auth_service.validate_oauth_state(state, session_store=self.mock_kv))
        self.assertTrue(is_valid)
        
        # Verify it is no longer in KV
        stored_val = self.run_async(self.mock_kv.get(f"csrf:{state}"))
        self.assertIsNone(stored_val)

    def test_kv_direct_state_validation_expired(self):
        """Verify validate_oauth_state returns False when the state has expired in KV."""
        state = self.run_async(auth_service.generate_oauth_state(expires_in=-10, session_store=self.mock_kv))
        
        # Validate state (should return False as it is expired)
        is_valid = self.run_async(auth_service.validate_oauth_state(state, session_store=self.mock_kv))
        self.assertFalse(is_valid)

    def test_kv_direct_jwt_revocation(self):
        """Verify revoking and verifying JWT works with KV store."""
        user_payload = {"sub": "test_user_kv", "email": "kv@worldtech.map", "name": "KV User"}
        token = auth_service.issue_jwt_token(user_payload, expires_in=1000)
        
        # Verify initially valid
        decoded = self.run_async(auth_service.verify_jwt_token(token, session_store=self.mock_kv))
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded["sub"], "test_user_kv")
        
        # Revoke the token
        revoked = self.run_async(auth_service.revoke_jwt_token(token, session_store=self.mock_kv))
        self.assertTrue(revoked)
        
        # Verify now invalid
        decoded_revoked = self.run_async(auth_service.verify_jwt_token(token, session_store=self.mock_kv))
        self.assertIsNone(decoded_revoked)

    def test_flask_endpoints_with_kv_state(self):
        """Verify full Flask authentication flow integrates with KV store."""
        # 1. Initialize login (generates state and stores in KV)
        resp_init = self.client.get('/api/auth/google')
        self.assertEqual(resp_init.status_code, 200)
        data_init = json.loads(resp_init.data)
        state = data_init["state"]
        
        # Confirm state is in KV
        stored_val = self.run_async(self.mock_kv.get(f"csrf:{state}"))
        self.assertEqual(stored_val, "1")
        
        # 2. Callback with valid state (should consume from KV and issue JWT)
        resp_callback = self.client.get(f'/api/auth/callback?code=mock_code_user1&state={state}')
        self.assertEqual(resp_callback.status_code, 200)
        data_callback = json.loads(resp_callback.data)
        token = data_callback["token"]
        
        # Confirm state is consumed (deleted from KV)
        stored_val_after = self.run_async(self.mock_kv.get(f"csrf:{state}"))
        self.assertIsNone(stored_val_after)
        
        # 3. Status check with token (should be authenticated)
        self.client.set_cookie('session_token', token)
        resp_status = self.client.get('/api/auth/status')
        self.assertEqual(resp_status.status_code, 200)
        self.assertTrue(json.loads(resp_status.data)["authenticated"])
        
        # 4. Logout (should revoke token in KV and clear cookie)
        resp_logout = self.client.post('/api/auth/logout')
        self.assertEqual(resp_logout.status_code, 200)
        
        # Verify token is indeed marked revoked in KV
        # Determine signature or jti
        decoded_claims = self.run_async(auth_service.verify_jwt_token(token)) # bypass KV to decode
        jti = decoded_claims["jti"]
        sig = token.split('.')[2]
        
        revoked_jti = self.run_async(self.mock_kv.get(f"revoked:{jti}"))
        revoked_sig = self.run_async(self.mock_kv.get(f"revoked:{sig}"))
        self.assertTrue(revoked_jti == "1" or revoked_sig == "1")

        # 5. Status check now (should be unauthenticated)
        resp_status_after = self.client.get('/api/auth/status')
        self.assertFalse(json.loads(resp_status_after.data)["authenticated"])

    def test_flask_endpoints_with_kv_environ_override(self):
        """Verify Flask app retrieves KV from request environment override if present."""
        # Unset global config.SESSION_STORE to force retrieving from environment
        config.SESSION_STORE = None
        
        # Initialize login passing mock_kv in environment overrides
        resp_init = self.client.get('/api/auth/google', environ_overrides={'SESSION_STORE': self.mock_kv})
        self.assertEqual(resp_init.status_code, 200)
        data_init = json.loads(resp_init.data)
        state = data_init["state"]
        
        # Confirm state is in KV
        stored_val = self.run_async(self.mock_kv.get(f"csrf:{state}"))
        self.assertEqual(stored_val, "1")

if __name__ == '__main__':
    print("\n======================================================================")
    print(" 🔒 CLOUDFLARE KV SESSION STORE INTEGRATION VERIFICATION HARNESS 🔒")
    print("======================================================================")
    unittest.main(verbosity=2)
