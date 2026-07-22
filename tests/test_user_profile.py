#!/usr/bin/env python3
"""
Test Suite: tests/test_user_profile.py
Verifies Requirement: User Profile Management & Persistence (R2).
Tests unauthenticated rejection, profile retrieval/default creation, mutable updates,
immutable field protection, and SQLite persistence across store re-initialization.
"""

import unittest
import sys
import os
import json
import asyncio

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.app import app
from backend import config
from backend.services import auth_service
from backend.utils.compatibility import SQLiteKVStore, SQLiteD1Database

class TestUserProfileAPI(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()
        
        # Use a separate SQLite DB for tests
        self.test_db_path = "tmp/test_user_profile.db"
        if os.path.exists(self.test_db_path):
            try:
                os.remove(self.test_db_path)
            except Exception:
                pass
                
        self.test_store = SQLiteKVStore(self.test_db_path)
        self._old_session_store = getattr(config, 'SESSION_STORE', None)
        config.SESSION_STORE = self.test_store
        
        self.test_db = SQLiteD1Database(self.test_db_path)
        self._old_db = getattr(config, 'DB', None)
        config.DB = self.test_db

    def tearDown(self):
        config.SESSION_STORE = self._old_session_store
        config.DB = self._old_db
        if os.path.exists(self.test_db_path):
            try:
                os.remove(self.test_db_path)
            except Exception:
                pass

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_unauthenticated_access_rejection(self):
        """Reject unauthenticated requests with HTTP 401."""
        # Test GET
        resp_get = self.client.get('/api/user/profile')
        self.assertEqual(resp_get.status_code, 401)
        self.assertIn("error", json.loads(resp_get.data))

        # Test POST
        resp_post = self.client.post('/api/user/profile', json={"bio": "My new bio"})
        self.assertEqual(resp_post.status_code, 401)
        self.assertIn("error", json.loads(resp_post.data))

    def test_profile_retrieval_and_default_creation(self):
        """Retrieve profile or create a default one for authenticated user."""
        user_payload = {
            "sub": "usr_test_123",
            "email": "tester@worldtech.map",
            "name": "Testy Tester",
            "picture": "https://lh3.googleusercontent.com/a/testphoto"
        }
        token = auth_service.issue_jwt_token(user_payload, expires_in=600)
        self.client.set_cookie('session_token', token)

        # Retrieve profile for the first time -> should create default
        resp = self.client.get('/api/user/profile')
        self.assertEqual(resp.status_code, 200)
        profile = json.loads(resp.data)
        
        # Verify default profile schema and matching JWT info
        self.assertEqual(profile["id"], "usr_test_123")
        self.assertEqual(profile["email"], "tester@worldtech.map")
        self.assertEqual(profile["name"], "Testy Tester")
        self.assertEqual(profile["picture"], "https://lh3.googleusercontent.com/a/testphoto")
        self.assertEqual(profile["bio"], "")
        self.assertEqual(profile["skills"], [])
        self.assertEqual(profile["preferred_location"], "")
        self.assertEqual(profile["job_preferences"], {})

        # Confirm it was persisted in the D1 database
        row = self.run_async(self.test_db.prepare("SELECT * FROM user_profiles WHERE id = ?").bind("usr_test_123").first())
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "usr_test_123")

    def test_profile_update_mutable_fields(self):
        """Update mutable fields on POST /api/user/profile."""
        user_payload = {
            "sub": "usr_test_123",
            "email": "tester@worldtech.map",
            "name": "Testy Tester",
            "picture": "https://lh3.googleusercontent.com/a/testphoto"
        }
        token = auth_service.issue_jwt_token(user_payload, expires_in=600)
        self.client.set_cookie('session_token', token)

        # Trigger default profile creation
        self.client.get('/api/user/profile')

        # Update mutable fields
        update_data = {
            "name": "Updated Name",
            "bio": "Expert developer.",
            "skills": ["python", "flask", "sqlite"],
            "preferred_location": "Bengaluru",
            "job_preferences": {"role": "Senior Engineer", "salary_min": 120000}
        }
        resp = self.client.post('/api/user/profile', json=update_data)
        self.assertEqual(resp.status_code, 200)
        profile = json.loads(resp.data)

        # Verify modifications
        self.assertEqual(profile["name"], "Updated Name")
        self.assertEqual(profile["bio"], "Expert developer.")
        self.assertEqual(profile["skills"], ["python", "flask", "sqlite"])
        self.assertEqual(profile["preferred_location"], "Bengaluru")
        self.assertEqual(profile["job_preferences"], {"role": "Senior Engineer", "salary_min": 120000})

        # Get profile again to verify retrieval matches updates
        resp_get = self.client.get('/api/user/profile')
        self.assertEqual(resp_get.status_code, 200)
        profile_retrieved = json.loads(resp_get.data)
        self.assertEqual(profile_retrieved["name"], "Updated Name")
        self.assertEqual(profile_retrieved["bio"], "Expert developer.")

    def test_profile_ignore_immutable_fields(self):
        """Reject/ignore attempts to modify immutable fields by restoring from verified JWT."""
        user_payload = {
            "sub": "usr_test_123",
            "email": "tester@worldtech.map",
            "name": "Testy Tester",
            "picture": "https://lh3.googleusercontent.com/a/testphoto"
        }
        token = auth_service.issue_jwt_token(user_payload, expires_in=600)
        self.client.set_cookie('session_token', token)

        # Trigger default profile creation
        self.client.get('/api/user/profile')

        # Try to modify id and email
        malicious_update = {
            "id": "hacker_id",
            "email": "hacker@worldtech.map",
            "name": "Hacker Name",
            "bio": "Trying to modify immutable fields."
        }
        resp = self.client.post('/api/user/profile', json=malicious_update)
        self.assertEqual(resp.status_code, 200)
        profile = json.loads(resp.data)

        # Immutable fields must remain unchanged
        self.assertEqual(profile["id"], "usr_test_123")
        self.assertEqual(profile["email"], "tester@worldtech.map")
        
        # Mutable fields should be updated
        self.assertEqual(profile["name"], "Hacker Name")
        self.assertEqual(profile["bio"], "Trying to modify immutable fields.")

    def test_sqlite_persistence_across_store_reinitialization(self):
        """Verify profile data is successfully persisted across store re-initialization."""
        user_payload = {
            "sub": "usr_test_123",
            "email": "tester@worldtech.map",
            "name": "Testy Tester"
        }
        token = auth_service.issue_jwt_token(user_payload, expires_in=600)
        self.client.set_cookie('session_token', token)

        # Create/update profile in first store setup
        self.client.get('/api/user/profile')
        update_data = {"bio": "Persisted bio."}
        self.client.post('/api/user/profile', json=update_data)

        # Re-initialize store with the exact same DB file
        new_store = SQLiteKVStore(self.test_db_path)
        config.SESSION_STORE = new_store

        # Retrieve profile again -> should be read from file and contain the same bio
        resp = self.client.get('/api/user/profile')
        self.assertEqual(resp.status_code, 200)
        profile = json.loads(resp.data)
        self.assertEqual(profile["bio"], "Persisted bio.")
        self.assertEqual(profile["email"], "tester@worldtech.map")

if __name__ == '__main__':
    unittest.main(verbosity=2)
