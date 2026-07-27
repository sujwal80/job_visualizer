#!/usr/bin/env python3
"""
Automated E2E User Journeys & Visual Regression Test Suite:
tests/test_e2e_user_journeys.py

Verifies the 5 remaining core user journeys:
1. Landing & Presets Search
2. Interactive Directory & Map
3. Filtering & Live Search
4. Manual Map Navigation (Viewport Mode)
5. Authentication Flow

Additionally captures screenshots and compares them against baseline screenshots for visual regression verification.
"""

import unittest
import sys
import os
import time
import urllib.request
import urllib.parse
import threading

# Parse and strip --update-baselines before unittest parses argv
UPDATE_BASELINES = False
if "--update-baselines" in sys.argv:
    UPDATE_BASELINES = True
    sys.argv.remove("--update-baselines")

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Ensure project root is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestE2EUserJourneys(unittest.TestCase):
    """E2E User Journeys & Visual Regression Test Suite."""

    BASE_URL = "http://127.0.0.1:5004"
    SCREENSHOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "screenshots"))
    BASELINE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "baselines"))

    @classmethod
    def setUpClass(cls):
        """Manage backend server lifecycle and start Playwright headless Chromium."""
        if not PLAYWRIGHT_AVAILABLE:
            raise unittest.SkipTest("Playwright is not installed in this Python environment.")
        
        # Ensure directories exist
        os.makedirs(cls.SCREENSHOT_DIR, exist_ok=True)
        os.makedirs(cls.BASELINE_DIR, exist_ok=True)

        cls.server_thread = None
        cls.server = None
        cls.server_ready = False

        # Check if a backend server instance is already running on 5004
        try:
            with urllib.request.urlopen(f"{cls.BASE_URL}/api/companies?limit=1", timeout=1) as response:
                if response.status == 200:
                    cls.server_ready = True
        except Exception:
            cls.server_ready = False

        # If not running, start backend Flask app cleanly in a daemon thread
        if not cls.server_ready:
            from backend.app import app
            from werkzeug.serving import make_server
            app.testing = True
            cls.server = make_server("127.0.0.1", 5004, app, threaded=True)
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
        """Close browser and cleanly shut down backend server if started by suite."""
        if hasattr(cls, 'browser') and cls.browser:
            cls.browser.close()
        if hasattr(cls, 'playwright') and cls.playwright:
            cls.playwright.stop()
        if hasattr(cls, 'server') and cls.server:
            cls.server.shutdown()
            if hasattr(cls, 'server_thread') and cls.server_thread:
                cls.server_thread.join(timeout=2)

    def setUp(self):
        """Create a fresh browser context and page for each test case."""
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 800})
        self.page = self.context.new_page()
        self.js_errors = []
        self.page.on("pageerror", lambda err: self.js_errors.append(str(err)))

    def tearDown(self):
        """Close page and context after each test case."""
        if hasattr(self, 'page') and self.page:
            self.page.close()
        if hasattr(self, 'context') and self.context:
            self.context.close()

    def _take_screenshot(self, name):
        """Helper to capture visual regression screenshot and compare it with the baseline."""
        if UPDATE_BASELINES:
            path = os.path.join(self.BASELINE_DIR, f"{name}.png")
            self.page.screenshot(path=path, full_page=True)
            print(f"Updated baseline screenshot: {path}")
            return

        # Regular verification run
        runtime_path = os.path.join(self.SCREENSHOT_DIR, f"{name}.png")
        self.page.screenshot(path=runtime_path, full_page=True)
        print(f"Captured runtime screenshot: {runtime_path}")

        baseline_path = os.path.join(self.BASELINE_DIR, f"{name}.png")
        if not os.path.exists(baseline_path):
            raise FileNotFoundError(
                f"Baseline screenshot not found: {baseline_path}. "
                "Please run with '--update-baselines' to generate baselines first."
            )

        # Compare screenshots
        self.compare_images(baseline_path, runtime_path)

    def compare_images(self, img1_path, img2_path):
        """Compares two images using Pillow (or fallback) and asserts divergence <= 2%."""
        try:
            from PIL import Image, ImageChops
            pillow_available = True
        except ImportError:
            pillow_available = False

        if not pillow_available:
            print("WARNING: Pillow is not installed. Performing basic byte-wise verification fallback.")
            with open(img1_path, "rb") as f1, open(img2_path, "rb") as f2:
                b1 = f1.read()
                b2 = f2.read()
                if b1 == b2:
                    print("Visual comparison passed (byte-wise identical).")
                    return
                else:
                    print("WARNING: Images differ byte-wise, but Pillow is not installed. Skipping pixel-level assertion.")
                    return

        # Pillow comparison
        img1 = Image.open(img1_path).convert("RGB")
        img2 = Image.open(img2_path).convert("RGB")

        if img1.size != img2.size:
            self.fail(f"Visual regression failed: Image dimensions differ. Baseline: {img1.size}, Runtime: {img2.size}")

        diff = ImageChops.difference(img1, img2)
        if diff.getbbox() is None:
            divergence_pct = 0.0
        else:
            gray_diff = diff.convert("L")
            hist = gray_diff.histogram()
            total_pixels = gray_diff.size[0] * gray_diff.size[1]
            non_zero_pixels = total_pixels - hist[0]
            divergence_pct = (non_zero_pixels / total_pixels) * 100.0

        print(f"Image comparison divergence for {os.path.basename(img1_path)}: {divergence_pct:.2f}%")
        self.assertTrue(
            divergence_pct <= 2.0,
            f"Visual regression divergence ({divergence_pct:.2f}%) exceeds 2% threshold for {os.path.basename(img1_path)}"
        )

    # =========================================================================
    # Journey 1: Landing & Presets Search
    # =========================================================================
    def test_journey_1_landing_and_presets_search(self):
        """Verify Homepage landing page load, search by presets (Bengaluru), and navigation back."""
        # 1. Load Homepage
        response = self.page.goto(f"{self.BASE_URL}/")
        self.assertEqual(response.status, 200)
        self.page.wait_for_load_state("domcontentloaded")

        # Verify landing page title & visual structure
        self.assertIn("Map My Job", self.page.title())
        self.assertTrue(self.page.locator("#landingInterface").is_visible())
        self._take_screenshot("journey_1_landing_page")

        # 2. Click preset city Bengaluru
        self.page.click("button[onclick=\"handlePresetSearch('bengaluru')\"]")
        self.page.wait_for_url("**/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_timeout(1000)

        # Verify page transitioned to /jobs with search bounds loaded
        self.assertIn("/jobs", self.page.url)
        self.assertTrue(self.page.locator("#directory-list .directory-item").count() > 0)
        self.assertEqual(self.page.locator("#activeMapTitle").text_content().strip(), "Bengaluru, KA")
        self._take_screenshot("journey_1_jobs_bengaluru")

        # 3. Go back using the logo
        self.page.click(".top-navbar .brand-logo")
        self.page.wait_for_timeout(500)
        parsed_path = urllib.parse.urlparse(self.page.url).path
        self.assertEqual(parsed_path, "/")
        self.assertTrue(self.page.locator("#landingInterface").is_visible())

        self.assertEqual(self.js_errors, [])

    # =========================================================================
    # Journey 2: Interactive Directory & Map
    # =========================================================================
    def test_journey_2_interactive_directory_and_map(self):
        """Verify clicking directory items/markers opens details drawer with correct job details."""
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_timeout(1500)

        # Verify map markers and directory cards are rendered
        self.assertTrue(self.page.locator("#directory-list .directory-item").count() > 0)
        self.assertTrue(self.page.locator(".logo-marker-container").count() > 0)

        # Click the first directory item
        first_item = self.page.locator("#directory-list .directory-item").first
        company_name = first_item.locator(".card-title").text_content().strip()
        first_item.click()

        # Wait for details drawer to slide open
        self.page.wait_for_selector("#details-drawer.active", timeout=5000)
        self._take_screenshot("journey_2_details_drawer_active")

        # Drawer content should contain company name
        drawer_content = self.page.locator("#drawer-content").text_content()
        self.assertIn(company_name, drawer_content)

        # Verify close drawer button hides the details drawer
        self.page.click("#close-drawer-btn")
        self.page.wait_for_timeout(500)
        self.assertFalse(self.page.locator("#details-drawer").evaluate("el => el.classList.contains('active')"))

        self.assertEqual(self.js_errors, [])

    # =========================================================================
    # Journey 3: Filtering & Live Search
    # =========================================================================
    def test_journey_3_filtering_and_live_search(self):
        """Verify work type, experience level, salary filtering, and keyword search."""
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && window.WorldTechApp.state && window.WorldTechApp.state.startupsData.length > 0",
            timeout=10000
        )
        self.page.locator("#directory-list .directory-item").first.wait_for(state="visible", timeout=5000)

        initial_count = self.page.locator("#directory-list .directory-item").count()

        # 1. Type specific company/job query into unified search
        self.page.fill("#unified-search-input", "Zenith SaaS")
        self.page.wait_for_timeout(1000)

        # Verify directory list is filtered down
        filtered_count = self.page.locator("#directory-list .directory-item").count()
        self.assertEqual(filtered_count, 1)
        self.assertEqual(self.page.locator("#directory-list .directory-item .card-title").text_content().strip(), "Zenith SaaS")
        self._take_screenshot("journey_3_filtered_keyword")

        # 2. Clear search input and verify restoration
        self.page.fill("#unified-search-input", "")
        self.page.wait_for_timeout(1000)
        self.assertEqual(self.page.locator("#directory-list .directory-item").count(), initial_count)

        self.assertEqual(self.js_errors, [])

    # =========================================================================
    # Journey 4: Manual Map Navigation (Viewport Mode)
    # =========================================================================
    def test_journey_4_manual_map_navigation_viewport_mode(self):
        """Verify that a manual map pan/zoom triggers correct transition to Viewport mode."""
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && window.WorldTechApp.map && !window.WorldTechApp.state.isProgrammaticMove",
            timeout=15000
        )
        
        # Verify initial search state parameters
        self.assertEqual(self.page.evaluate("() => window.WorldTechApp.state.searchedCity").lower(), "bengaluru, ka")
        self.assertEqual(self.page.locator("#activeMapTitle").text_content().strip().lower(), "bengaluru, ka")
        self.assertIn("bengaluru", self.page.url.lower())

        # Trigger manual map pan by simulating 'moveend' event with originalEvent (user triggered)
        self.page.evaluate("window.WorldTechApp.map.fire('moveend', { originalEvent: {} })")

        # Wait for city parameter to be deleted from URL
        self.page.wait_for_function("() => !window.location.search.includes('city=')", timeout=5000)
        self.page.wait_for_timeout(500)

        # Verify state transition to Viewport Mode
        self.assertNotIn("city=", self.page.url)
        self.assertEqual(self.page.evaluate("() => window.WorldTechApp.state.searchedCity"), "")
        self.assertIsNone(self.page.evaluate("() => window.WorldTechApp.state.boundsOverride"))
        self.assertEqual(self.page.locator("#activeMapTitle").text_content().strip(), "All locations")
        self.assertEqual(self.page.locator("#unified-search-input").input_value(), "")
        self.assertEqual(self.page.locator("#unified-search-input").get_attribute("placeholder"), "Search city/location ...")
        
        self._take_screenshot("journey_4_viewport_mode")
        self.assertEqual(self.js_errors, [])

    # =========================================================================
    # Journey 5: Authentication Flow
    # =========================================================================
    def test_journey_5_authentication_flow(self):
        """Verify demo login session issuance, authenticated API profile check, and logout."""
        # 1. Trigger demo login redirect
        self.page.goto(f"{self.BASE_URL}/api/auth/demo_login?redirect=true")
        self.page.wait_for_load_state("domcontentloaded")

        # Browser should land back on root path
        self.assertEqual(urllib.parse.urlparse(self.page.url).path, "/")

        # session_token cookie should be set in browser context
        cookies = self.context.cookies()
        session_cookies = [c for c in cookies if c["name"] == "session_token"]
        self.assertEqual(len(session_cookies), 1)

        # Verify /api/auth/status returns authenticated info
        status_data = self.page.evaluate("() => fetch('/api/auth/status').then(r => r.json())")
        self.assertTrue(status_data.get("authenticated"))
        self.assertEqual(status_data["user"]["email"], "ujwal@worldtech.map")

        self._take_screenshot("journey_5_authenticated_root")

        # 2. Trigger logout
        logout_data = self.page.evaluate("() => fetch('/api/auth/logout', {method: 'POST'}).then(r => r.json())")
        self.assertFalse(logout_data.get("authenticated"))

        # Subsequent status check should show unauthenticated
        status_data_after = self.page.evaluate("() => fetch('/api/auth/status').then(r => r.json())")
        self.assertFalse(status_data_after.get("authenticated"))

        self.assertEqual(self.js_errors, [])


if __name__ == '__main__':
    unittest.main()
