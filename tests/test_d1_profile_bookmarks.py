#!/usr/bin/env python3
import unittest
import sys
import os
import json
import asyncio

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.app import app
from backend.services import auth_service
from backend import config

class TestD1ProfileAndBookmarks(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()
        auth_service.reset_auth_stores()
        
        # Clear/initialize test tables for local D1
        # Since config.DB points to the SQLite D1 database, we can run exec to clear tables
        asyncio.run(config.DB.exec("DELETE FROM user_profiles; DELETE FROM bookmarks;"))

        # Issue token for a test user
        self.test_user = {
            "sub": "user_d1_test_999",
            "email": "d1_test@worldtech.map",
            "name": "D1 Tester",
            "picture": "https://lh3.googleusercontent.com/mock_d1_pic"
        }
        self.token = auth_service.issue_jwt_token(self.test_user)
        self.client.set_cookie('session_token', self.token)

    def test_01_profile_crud(self):
        # 1. Get default profile (should insert default into DB and return it)
        resp = self.client.get('/api/user/profile')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data["id"], self.test_user["sub"])
        self.assertEqual(data["email"], self.test_user["email"])
        self.assertEqual(data["name"], self.test_user["name"])
        self.assertEqual(data["picture"], self.test_user["picture"])
        self.assertEqual(data["bio"], "")
        self.assertEqual(data["skills"], [])
        self.assertEqual(data["job_preferences"], {})

        # 2. Update profile
        update_payload = {
            "name": "Updated Tester Name",
            "bio": "Expert in D1 integration",
            "skills": ["Python", "Cloudflare", "SQL"],
            "job_preferences": {"role": "Senior Engineer", "salary_min": 120000}
        }
        resp = self.client.post('/api/user/profile', json=update_payload)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data["name"], "Updated Tester Name")
        self.assertEqual(data["bio"], "Expert in D1 integration")
        self.assertEqual(data["skills"], ["Python", "Cloudflare", "SQL"])
        self.assertEqual(data["job_preferences"], {"role": "Senior Engineer", "salary_min": 120000})
        # Immutable fields should remain unchanged
        self.assertEqual(data["email"], self.test_user["email"])
        self.assertEqual(data["picture"], self.test_user["picture"])

        # 3. Fetch again to ensure persistence
        resp = self.client.get('/api/user/profile')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data["name"], "Updated Tester Name")
        self.assertEqual(data["bio"], "Expert in D1 integration")
        self.assertEqual(data["skills"], ["Python", "Cloudflare", "SQL"])

    def test_02_bookmarks_crud(self):
        # 1. GET bookmarks (initially empty list)
        resp = self.client.get('/api/user/bookmarks')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.data), [])

        # 2. POST bookmark (company_id = "1")
        resp = self.client.post('/api/user/bookmarks', json={"company_id": "1"})
        self.assertEqual(resp.status_code, 201)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])
        self.assertEqual(data["bookmark"]["company_id"], "1")
        self.assertEqual(data["bookmark"]["user_id"], self.test_user["sub"])
        
        # 3. GET bookmarks again (should contain the added bookmark)
        resp = self.client.get('/api/user/bookmarks')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["company_id"], "1")
        # Ensure company name is populated from startups.json (id 1 is Kora.AI)
        self.assertEqual(data[0]["name"], "Kora.AI")
        self.assertIsNotNone(data[0]["saved_at"])

        # 4. DELETE bookmark by company_id
        resp = self.client.delete('/api/user/bookmarks', json={"company_id": "1"})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])

        # 5. GET bookmarks (should be empty again)
        resp = self.client.get('/api/user/bookmarks')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.data), [])

if __name__ == "__main__":
    unittest.main()
