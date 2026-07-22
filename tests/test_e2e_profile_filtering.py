#!/usr/bin/env python3
"""
E2E Integration Test Suite for User Profile Management and Auto-Filter Flow.
Verifies R4 integration requirements:
1. Log in via demo sandbox login.
2. Verify user name and avatar are rendered on header.
3. Open Profile Modal by clicking "View Profile".
4. Update profile details: name, bio, skills, location, and job preferences.
5. Click Save and verify profile POST call succeeds, UI updates, and modal closes.
6. Verify auto-filter application: when transitioning/loading the app page, filters in sidebar are automatically selected and a filtered search is triggered.
7. Verify logout triggers a redirect/reload and resets UI to anonymous view.
"""

import unittest
import sys
import os
import time
import urllib.request
import urllib.parse
import threading

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Ensure project root is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.app import app
from backend import config
from backend.utils.compatibility import SQLiteKVStore, SQLiteD1Database


class TestE2EProfileFiltering(unittest.TestCase):
    BASE_URL = "http://127.0.0.1:5005"
    TEST_DB_PATH = "tmp/test_e2e_profile_filtering.db"

    @classmethod
    def setUpClass(cls):
        """Manage backend server lifecycle and start Playwright headless Chromium."""
        if not PLAYWRIGHT_AVAILABLE:
            raise unittest.SkipTest("Playwright is not installed in this Python environment.")

        # Ensure temp directories exist
        os.makedirs("tmp", exist_ok=True)
        if os.path.exists(cls.TEST_DB_PATH):
            try:
                os.remove(cls.TEST_DB_PATH)
            except Exception:
                pass

        # Re-route the session store to a clean test-specific SQLite file
        cls.test_store = SQLiteKVStore(cls.TEST_DB_PATH)
        cls._old_session_store = getattr(config, 'SESSION_STORE', None)
        config.SESSION_STORE = cls.test_store

        cls.test_db = SQLiteD1Database(cls.TEST_DB_PATH)
        cls._old_db = getattr(config, 'DB', None)
        config.DB = cls.test_db

        cls.server_thread = None
        cls.server = None
        cls.server_ready = False

        # Start backend app on port 5005
        from werkzeug.serving import make_server
        app.testing = True
        cls.server = make_server("127.0.0.1", 5005, app, threaded=True)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

        # Wait for server to become ready
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"{cls.BASE_URL}/api/companies?limit=1", timeout=1) as response:
                    if response.status == 200:
                        cls.server_ready = True
                        break
            except Exception:
                time.sleep(0.2)

        if not cls.server_ready:
            raise RuntimeError(f"Backend Flask server could not be started or reached at {cls.BASE_URL}")

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        """Close browser and cleanly shut down backend server."""
        if hasattr(cls, 'browser') and cls.browser:
            cls.browser.close()
        if hasattr(cls, 'playwright') and cls.playwright:
            cls.playwright.stop()
        if hasattr(cls, 'server') and cls.server:
            cls.server.shutdown()
            if hasattr(cls, 'server_thread') and cls.server_thread:
                cls.server_thread.join(timeout=2)
        config.SESSION_STORE = cls._old_session_store
        config.DB = cls._old_db
        if os.path.exists(cls.TEST_DB_PATH):
            try:
                os.remove(cls.TEST_DB_PATH)
            except Exception:
                pass

    def setUp(self):
        """Create a fresh browser context and page for each test case."""
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 800})
        self.page = self.context.new_page()
        self.js_errors = []
        self.page.on("pageerror", lambda err: self.js_errors.append(str(err)))
        self.page.on("console", lambda msg: print(f"[CONSOLE] {msg.text}"))

    def tearDown(self):
        """Close page and context after each test case."""
        if hasattr(self, 'page') and self.page:
            self.page.close()
        if hasattr(self, 'context') and self.context:
            self.context.close()

    def test_profile_edit_and_auto_filter_flow(self):
        """Test complete profile editing, modal save, UI update, auto-filter application, and logout."""
        # 1. Load root path as anonymous user -> Login button should be visible
        self.page.goto(f"{self.BASE_URL}/")
        self.page.wait_for_load_state("domcontentloaded")

        login_buttons = self.page.locator(".auth-anon a")
        self.assertTrue(login_buttons.first.is_visible())
        
        # 2. Perform Demo Sandbox Login
        self.page.goto(f"{self.BASE_URL}/api/auth/demo_login?redirect=true")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_timeout(1000)

        # 3. Check page has user dropdown/avatar instead of login
        self.assertFalse(self.page.locator("#landingInterface .auth-anon").is_visible())
        user_dropdown_toggle = self.page.locator("#landingInterface .user-dropdown-toggle")
        self.assertTrue(user_dropdown_toggle.is_visible())
        self.assertIn("Ujwal Singh", user_dropdown_toggle.text_content())

        # 4. Open User Profile Dropdown & Click View Profile
        user_dropdown_toggle.click()
        self.page.wait_for_timeout(200)
        
        view_profile_btn = self.page.locator("#landingInterface .view-profile-btn")
        self.assertTrue(view_profile_btn.is_visible())
        view_profile_btn.click()

        # 5. Verify Profile Modal opens and fields populate
        self.page.wait_for_selector("#profile-modal:not(.hidden)", timeout=3000)
        
        # Verify initial values in modal
        self.assertEqual(self.page.locator("#profile-modal-email").text_content(), "ujwal@worldtech.map")
        self.assertEqual(self.page.locator("#profile-name").input_value(), "Ujwal Singh")

        # 6. Update Profile Fields
        self.page.fill("#profile-name", "Ujwal Edited")
        self.page.fill("#profile-bio", "A passionate tester of map-based systems.")
        self.page.fill("#profile-skills", "Python, Playwright, Tailwind")
        self.page.fill("#profile-location", "Bengaluru")
        
        # Set job preferences
        self.page.select_option("#profile-pref-work-type", "remote")
        self.page.select_option("#profile-pref-exp-level", "senior")
        self.page.fill("#profile-pref-min-salary", "15")

        # Submit the profile form
        self.page.click('#profile-form button[type="submit"]')
        
        # Modal should close
        self.page.wait_for_selector("#profile-modal", state="hidden", timeout=3000)

        # Header user name should update
        self.page.wait_for_timeout(500)
        self.assertIn("Ujwal Edited", user_dropdown_toggle.text_content())

        # 7. Verify Auto-Filter application by navigating to jobs page (via preset search or direct URL)
        # We navigate to jobs page for Bengaluru
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_timeout(1500)

        # Sidebar filters should automatically reflect preferences: remote, senior, 15
        self.assertEqual(self.page.locator("#filter-work-type").input_value(), "remote")
        self.assertEqual(self.page.locator("#filter-exp-level").input_value(), "senior")
        self.assertEqual(self.page.locator("#filter-salary-min").input_value(), "15")

        # Verify that URL search query filters or the Javascript state filters include these
        current_filters = self.page.evaluate("() => window.WorldTechApp.state.currentFilters")
        self.assertEqual(current_filters.get("work_type"), "remote")
        self.assertEqual(current_filters.get("exp_level"), "senior")
        self.assertEqual(current_filters.get("salary_min"), "15")

        # 8. Test Logout
        user_dropdown_toggle = self.page.locator("#app-container .user-dropdown-toggle")
        user_dropdown_toggle.click()
        self.page.wait_for_timeout(200)
        
        logout_btn = self.page.locator("#app-container .logout-btn")
        self.assertTrue(logout_btn.is_visible())
        logout_btn.click()
        
        # Wait for the login button to reappear on the app header (since we reload current /jobs page)
        self.page.wait_for_selector("#app-container .auth-anon", state="visible", timeout=5000)
        self.assertTrue(self.page.locator("#app-container .auth-anon").is_visible())
        self.assertFalse(self.page.locator("#app-container .auth-user").is_visible())

        self.assertEqual(self.js_errors, [])


if __name__ == '__main__':
    unittest.main()
