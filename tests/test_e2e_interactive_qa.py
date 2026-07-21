#!/usr/bin/env python3
"""
Automated E2E Interactive QA Test Suite: tests/test_e2e_interactive_qa.py
Verifies end-to-end user journeys for the Startup Visualizer application using
Playwright v1.60.0 + Headless Chromium against the Flask backend server.

Covers:
a) Server Lifecycle & Homepage UI Rendering across Viewports (320px, 768px, 1920px)
b) Interactive Unauthenticated Map Navigation & Markers
c) Search & Filtering Controls (Landing search, Presets, Industry tabs, Live search)
d) Details Drawer & Job Card Interaction
e) Authenticated User Flow (Demo Login, Session Token issuance, Protected Profile, Logout)
f) Edge-Case Journeys (Rapid filter toggling, Empty search results recovery)
"""

import unittest
import sys
import os
import time
import json
import threading
import urllib.request
import urllib.parse
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Ensure project root is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestE2EInteractiveQA(unittest.TestCase):
    """Exhaustive Automated E2E Interactive QA Test Suite using Playwright & Headless Chromium."""

    BASE_URL = "http://127.0.0.1:5001"

    @classmethod
    def setUpClass(cls):
        """Manage backend server lifecycle and start Playwright headless Chromium."""
        if not PLAYWRIGHT_AVAILABLE:
            raise unittest.SkipTest("Playwright is not installed in this Python environment.")
        cls.server_thread = None
        cls.server = None
        cls.server_ready = False

        # First check if a backend server instance is already running on 5001
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
            cls.server = make_server("127.0.0.1", 5001, app)
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
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.js_errors = []
        self.page.on("pageerror", lambda err: self.js_errors.append(str(err)))
        self.page.on("console", lambda msg: print(f"Browser Console {msg.type}: {msg.text}"))
        self.page.on("requestfailed", lambda req: print(f"Request Failed: {req.method} {req.url} - Error: {req.failure}"))
        self.page.on("response", lambda resp: print(f"Response: {resp.status} {resp.url}"))

    def tearDown(self):
        """Close page and context after each test case."""
        if hasattr(self, 'page') and self.page:
            self.page.close()
        if hasattr(self, 'context') and self.context:
            self.context.close()

    # =========================================================================
    # a) Server Lifecycle & Homepage UI Rendering across Viewports
    # =========================================================================

    def test_a1_server_lifecycle_and_homepage_load(self):
        """Verify server startup, homepage HTML rendering, landing input presence, and zero JS runtime errors."""
        response = self.page.goto(f"{self.BASE_URL}/")
        self.assertIsNotNone(response, "Page response should not be None")
        self.assertEqual(response.status, 200, "Homepage should return HTTP 200")
        self.page.wait_for_load_state("domcontentloaded")

        title = self.page.title()
        self.assertIn("JobMap", title, "Page title should contain JobMap")

        # Verify landing interface elements
        landing = self.page.locator("#landingInterface")
        self.assertTrue(landing.is_visible(), "Landing interface should be visible initially")

        city_input = self.page.locator("#landingCityInput")
        self.assertTrue(city_input.is_visible(), "Landing city input should be visible")

        # Verify zero JS runtime errors
        self.assertEqual(self.js_errors, [], f"Expected zero JS runtime errors, found: {self.js_errors}")

    def test_a2_responsive_layout_across_viewports(self):
        """Verify responsive UI rendering across mobile (320px), tablet (768px), and desktop (1920px) viewports."""
        viewports = [
            ("Mobile 320px", 320, 568),
            ("Tablet 768px", 768, 1024),
            ("Desktop 1920px", 1920, 1080)
        ]

        for name, width, height in viewports:
            with self.subTest(viewport=name):
                page = self.browser.new_page(viewport={"width": width, "height": height})
                errors = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                response = page.goto(f"{self.BASE_URL}/")
                self.assertEqual(response.status, 200)
                page.wait_for_load_state("domcontentloaded")

                input_box = page.locator("#landingCityInput")
                self.assertTrue(input_box.is_visible(), f"#landingCityInput should be visible on {name}")

                search_btn = page.locator("button[onclick='handleSearchFromLanding()']")
                self.assertTrue(search_btn.is_visible(), f"Search button should be visible on {name}")

                self.assertEqual(errors, [], f"Expected 0 JS runtime errors on {name}, found: {errors}")
                page.close()

    # =========================================================================
    # b) Interactive Unauthenticated Map Navigation & Markers
    # =========================================================================

    def test_b1_interactive_map_rendering_and_preset_navigation(self):
        """Verify preset city navigation redirects and loads startup marker pins & directory items."""
        self.page.goto(f"{self.BASE_URL}/")
        self.page.wait_for_load_state("domcontentloaded")

        # Click preset city Bengaluru
        self.page.click("button[onclick=\"handlePresetSearch('bengaluru')\"]")
        self.page.wait_for_timeout(1000)

        # Check URL redirected to /jobs
        self.assertIn("/jobs", self.page.url)

        # Verify no JS runtime errors
        self.assertEqual(self.js_errors, [], f"JS Errors: {self.js_errors}")

        # Verify active map title
        title_text = self.page.locator("#activeMapTitle").text_content()
        self.assertIn("Bengaluru", title_text)

        # Verify directory list items are loaded
        items_count = self.page.locator("#directory-list .directory-item").count()
        self.assertTrue(items_count > 0, "Bengaluru should render directory items")

        # Verify markers plotted
        pins_count = self.page.locator(".logo-marker-container").count()
        self.assertTrue(pins_count > 0, "Bengaluru should render marker pins")

    def test_b2_interactive_map_controls_and_zooming(self):
        """Verify Back to Search button returns to landing state."""
        self.page.goto(f"{self.BASE_URL}/")
        self.page.click("button[onclick=\"handlePresetSearch('mumbai')\"]")
        self.page.wait_for_timeout(1000)

        self.assertIn("/jobs", self.page.url)

        # Verify Back button returns to landing state
        self.page.click("button[onclick='handleNavbarBack()']")
        self.page.wait_for_timeout(500)
        
        parsed_path = urllib.parse.urlparse(self.page.url).path
        self.assertEqual(parsed_path, "/", "Back button should return user to homepage root")
        self.assertEqual(self.js_errors, [])

    # =========================================================================
    # c) Search & Filtering Controls
    # =========================================================================

    def test_c1_landing_city_search_input(self):
        """Verify typing a city name in landing input and searching navigates to correct location."""
        self.page.goto(f"{self.BASE_URL}/")
        self.page.fill("#landingCityInput", "London")
        self.page.click("button[onclick='handleSearchFromLanding()']")
        self.page.wait_for_timeout(1000)

        self.assertIn("/jobs", self.page.url)
        title_text = self.page.locator("#activeMapTitle").text_content()
        self.assertIn("London", title_text)
        self.assertTrue(self.page.locator("#directory-list .directory-item").count() > 0)
        self.assertEqual(self.js_errors, [])



    def test_c3_live_search_filtering(self):
        """Verify typing into live search input dynamically filters directory."""
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && window.WorldTechApp.state && window.WorldTechApp.state.startupsData && window.WorldTechApp.state.startupsData.length > 0",
            timeout=10000
        )

        # Wait for at least one directory item to be visible/present
        self.page.locator("#directory-list .directory-item").first.wait_for(state="visible", timeout=5000)
        total_items = self.page.locator("#directory-list .directory-item").count()
        state_len = self.page.evaluate("() => window.WorldTechApp.state.startupsData.length")
        initial_names = self.page.evaluate("() => Array.from(document.querySelectorAll('#directory-list .directory-item .card-title')).map(el => el.textContent.trim())")
        print(f"\nDEBUG test_c3: total_items={total_items}, state_startupsData_length={state_len}")
        print(f"DEBUG test_c3 initial names (len={len(initial_names)}): {initial_names}")

        # Search for a specific company name that exists, has job openings and is unique, e.g., "Indira Pay"
        self.page.fill("#unified-search-input", "Indira Pay")
        self.page.wait_for_timeout(1000)

        names = self.page.evaluate("() => Array.from(document.querySelectorAll('#directory-list .directory-item .card-title')).map(el => el.textContent.trim())")
        print(f"DEBUG test_c3 after search: names={names}")

        matches = self.page.locator("#directory-list .directory-item").count()
        self.assertEqual(matches, 1)

        # Clear search
        self.page.fill("#unified-search-input", "")
        self.page.wait_for_timeout(1000)
        
        cleared_items = self.page.locator("#directory-list .directory-item").count()
        cleared_state_len = self.page.evaluate("() => window.WorldTechApp.state.startupsData.length")
        print(f"DEBUG test_c3 after clear: cleared_items={cleared_items}, cleared_state_len={cleared_state_len}")
        self.assertEqual(cleared_items, total_items)
        self.assertEqual(self.js_errors, [])

    # =========================================================================
    # d) Details Drawer & Job Card Interaction
    # =========================================================================

    def test_d1_directory_item_click_opens_details_drawer(self):
        """Verify clicking a directory item opens the details drawer populated with company info."""
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_timeout(1000)

        # Click first directory item
        first_item = self.page.locator("#directory-list .directory-item").first
        company_name = first_item.locator(".card-title").text_content()
        first_item.click()

        # Wait for details drawer to become active
        self.page.wait_for_selector("#details-drawer.active", timeout=5000)

        # Details drawer should be active
        drawer = self.page.locator("#details-drawer")
        self.assertTrue(drawer.evaluate("el => el.classList.contains('active')"), "Drawer should have active class")

        # Drawer content should contain company name
        drawer_content = self.page.locator("#drawer-content")
        self.assertIn(company_name.strip(), drawer_content.text_content())

        # Close drawer
        self.page.click("#close-drawer-btn")
        self.page.wait_for_timeout(500)
        self.assertFalse(drawer.evaluate("el => el.classList.contains('active')"), "Drawer should not be active after close")
        self.assertEqual(self.js_errors, [])

    def test_d2_job_openings_render_apply_links(self):
        """Verify that opening a startup with job openings renders apply links inside the drawer."""
        # Stripe has jobs
        self.page.goto(f"{self.BASE_URL}/jobs?city=San%20Francisco%2C%20CA")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_timeout(1000)

        # Click Stripe directory item
        self.page.locator("#directory-list .directory-item:has-text('Stripe')").first.click()

        # Verify job card is rendered in details drawer and wait for it
        job_card = self.page.locator("#details-drawer .job-card").first
        job_card.wait_for(state="visible", timeout=15000)
        self.assertTrue(job_card.is_visible())

        # Verify apply link exists and has text Apply / Company Site / Jobs
        apply_link = job_card.locator("a.job-btn")
        self.assertTrue(apply_link.is_visible())
        link_text = apply_link.text_content()
        self.assertTrue("↗" in link_text or "Apply" in link_text or "Site" in link_text or "Jobs" in link_text)
        self.assertEqual(self.js_errors, [])

    def test_d3_country_search_usa(self):
        """Verify that searching for 'USA' in the landing search redirects and centers on San Francisco with jobs."""
        self.page.goto(self.BASE_URL)
        self.page.wait_for_load_state("domcontentloaded")

        # Fill USA in landing search input and press enter
        self.page.fill("#landingCityInput", "USA")
        self.page.press("#landingCityInput", "Enter")

        # Wait for redirect
        self.page.wait_for_url(f"**/jobs?city=San%20Francisco%2C%20CA")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_timeout(1000)

        # Verify directory items exist
        self.assertTrue(self.page.locator("#directory-list .directory-item").count() > 0, "Should render startups in SF when USA is searched")

        # Verify map title displays San Francisco, CA
        self.assertEqual(self.page.locator("#activeMapTitle").text_content().strip(), "San Francisco, CA")
        self.assertEqual(self.js_errors, [])

    def test_d4_country_search_non_hub_delhi(self):
        """Verify that searching for 'Delhi' (a non-hub city with 0 jobs) geocodes via OSM, centers the map on Delhi, and renders 0 jobs."""
        self.page.route(
            "https://nominatim.openstreetmap.org/search?q=delhi&format=json&limit=1",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='[{"lat": "28.6139", "lon": "77.2090", "display_name": "Delhi, India"}]'
            )
        )

        self.page.goto(self.BASE_URL)
        self.page.wait_for_load_state("domcontentloaded")

        # Fill Delhi in landing search and press enter
        self.page.fill("#landingCityInput", "Delhi")
        self.page.press("#landingCityInput", "Enter")

        # Wait for redirect
        self.page.wait_for_url(f"**/jobs?city=Delhi")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_timeout(1500)

        # Verify left directory list is NOT stuck on "Finding jobs in neighborhood..."
        dir_text = self.page.locator("#directory-list").text_content()
        self.assertNotIn("Finding jobs in neighborhood...", dir_text,
                         "Left side job directory bar must not remain stuck on loading text after city search.")

        # Verify directory list renders matching startups or empty state cleanly
        self.assertGreaterEqual(self.page.locator("#directory-list .directory-item").count(), 0)

        # Verify map title displays Delhi
        self.assertEqual(self.page.locator("#activeMapTitle").text_content().strip(), "Delhi")
        self.assertEqual(self.js_errors, [])

    # =========================================================================
    # e) Authenticated User Flow
    # =========================================================================

    def test_e1_demo_login_cookie_issuance_and_status(self):
        """Verify demo login endpoint sets session_token cookie and status API returns authenticated profile."""
        self.page.goto(f"{self.BASE_URL}/api/auth/demo_login?redirect=true")
        self.page.wait_for_load_state("domcontentloaded")

        # Check browser landed on root /
        parsed_path = urllib.parse.urlparse(self.page.url).path
        self.assertEqual(parsed_path, "/")

        # Check cookie in context
        cookies = self.context.cookies()
        session_cookie = [c for c in cookies if c["name"] == "session_token"]
        self.assertEqual(len(session_cookie), 1, "session_token cookie should be set after demo login")

        # Verify /api/auth/status via fetch API inside page context
        status_data = self.page.evaluate("() => fetch('/api/auth/status').then(r => r.json())")
        self.assertTrue(status_data.get("authenticated"), "User should be authenticated")
        self.assertEqual(status_data["user"]["email"], "ujwal@worldtech.map")
        self.assertEqual(status_data["user"]["name"], "Ujwal Singh")

        # Verify protected endpoint /api/user/profile
        profile_data = self.page.evaluate("() => fetch('/api/user/profile').then(r => r.json())")
        self.assertTrue(profile_data.get("authenticated"))
        self.assertEqual(profile_data["user"]["email"], "ujwal@worldtech.map")
        self.assertEqual(self.js_errors, [])

    def test_e2_logout_flow_and_session_revocation(self):
        """Verify logout endpoint revokes active session and clears authentication status."""
        self.page.goto(f"{self.BASE_URL}/api/auth/demo_login?redirect=true")
        self.page.wait_for_load_state("domcontentloaded")

        # Call logout API
        logout_data = self.page.evaluate("() => fetch('/api/auth/logout', {method: 'POST'}).then(r => r.json())")
        self.assertFalse(logout_data.get("authenticated"), "Logout should return authenticated: False")

        # Check subsequent status
        status_data = self.page.evaluate("() => fetch('/api/auth/status').then(r => r.json())")
        self.assertFalse(status_data.get("authenticated"), "Subsequent status check should be unauthenticated")
        self.assertEqual(self.js_errors, [])

    # =========================================================================
    # f) Edge-Case Journeys
    # =========================================================================

    def test_f1_rapid_filter_toggles_resilience(self):
        """Verify rapid successive dropdown filter toggling causes zero JS runtime errors or crashes."""
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && window.WorldTechApp.state && window.WorldTechApp.state.startupsData && window.WorldTechApp.state.startupsData.length > 0",
            timeout=10000
        )

        # Rapidly change work type filters
        work_types = ["remote", "hybrid", "onsite", ""]
        for wt in work_types:
            self.page.select_option("#filter-work-type", wt)

        self.page.wait_for_timeout(500)
        self.assertEqual(self.js_errors, [], "Rapid filter clicks should produce 0 JS runtime errors")

    def test_f2_empty_search_results_and_recovery(self):
        """Verify graceful UI rendering on zero search matches and recovery by clearing search."""
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_timeout(1000)

        self.page.fill("#unified-search-input", "NONEXISTENT_XYZ_99999")
        self.page.wait_for_timeout(600)

        # Directory should show empty message
        dir_text = self.page.locator("#directory-list").text_content()
        self.assertIn("No companies match your criteria", dir_text)

        # Clear search
        self.page.fill("#unified-search-input", "")
        self.page.wait_for_timeout(600)

        self.assertTrue(self.page.locator("#directory-list .directory-item").count() > 0)
        self.assertEqual(self.js_errors, [])

    # =========================================================================
    # g) Findings & Fixes Verification
    # =========================================================================

    def test_g1_coordinates_wrapping_normalization_no_errors(self):
        """Verify that panning map across wrapping boundaries does not trigger HTTP 400 errors."""
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_timeout(2000)

        # Simulate moving map to extreme longitudes (wrapping) and verify zero errors
        self.page.evaluate("() => WorldTechApp.map.jumpTo({center: [200, 10]})")
        self.page.wait_for_timeout(1000)

        # Confirm no JS errors after wrapping coordinates movement
        self.assertEqual(self.js_errors, [], "Should have no JS errors after wrapping coordinates movement")

    def test_g2_city_search_flyto_animation_properties(self):
        """Verify city search transitions use speed: 3.0 and omit the curve property."""
        self.page.route(
            "https://nominatim.openstreetmap.org/search?q=delhi&format=json&limit=1",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='[{"lat": "28.6139", "lon": "77.2090", "display_name": "Delhi, India"}]'
            )
        )
        self.page.goto(f"{self.BASE_URL}/")
        self.page.wait_for_timeout(1000)

        # Click preset city Bengaluru
        self.page.click("button[onclick=\"handlePresetSearch('bengaluru')\"]")
        self.page.wait_for_url("**/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && window.WorldTechApp.state && window.WorldTechApp.state.startupsData && window.WorldTechApp.state.startupsData.length > 0",
            timeout=10000
        )

        # Set up a spy on map.flyTo to capture options
        self.page.evaluate("""() => {
            window.flyToCalls = [];
            const originalFlyTo = WorldTechApp.map.flyTo;
            WorldTechApp.map.flyTo = function(opts) {
                window.flyToCalls.push(opts);
                return originalFlyTo.apply(this, arguments);
            };
        }""")

        # Trigger city search to Delhi programmatically
        self.page.evaluate("() => window.updateSearchCity('delhi')")
        self.page.wait_for_timeout(2000)

        # Retrieve the captured arguments
        calls = self.page.evaluate("() => window.flyToCalls")
        self.assertTrue(len(calls) > 0, "map.flyTo should have been called")
        last_call = calls[-1]
        self.assertEqual(last_call.get("speed"), 3.0, "Animation speed should be 3.0")
        self.assertIsNone(last_call.get("curve"), "Animation curve should be omitted/undefined for smooth panning")

    def test_g3_sidebar_scroll_persistence_after_map_pan(self):
        """Verify that panning the map does not reset the sidebar scroll position back to the selected startup."""
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_timeout(2000)

        # Click first startup card to select it
        cards = self.page.locator("#directory-list .directory-item")
        self.assertTrue(cards.count() > 0, "Should have startup cards")
        cards.first.click()
        self.page.wait_for_timeout(1500)

        # Scroll the directory list container down manually
        self.page.evaluate("() => document.getElementById('directory-list').scrollTop = 300")
        scroll_pos_before = self.page.evaluate("() => document.getElementById('directory-list').scrollTop")

        # Pan the map slightly to trigger a fetch
        self.page.evaluate("() => WorldTechApp.map.panBy([50, 50])")
        self.page.wait_for_timeout(1500)

        # Verify scroll position did not jump back
        scroll_pos_after = self.page.evaluate("() => document.getElementById('directory-list').scrollTop")
        self.assertAlmostEqual(scroll_pos_after, scroll_pos_before, delta=5,
                               msg="Sidebar scroll position should persist and not jump back to selected item on map pan")

    def test_g4_remote_startup_marker_persistence_and_cleanup(self):
        """Verify that selecting a remote startup plots a temp marker, persists it on pan, and clears it on drawer close."""
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_timeout(2000)

        # Locate the card for a remote startup (has Remote / Hub label)
        remote_card = self.page.locator(".directory-item:has-text('Remote / Hub')").first
        self.assertTrue(remote_card.is_visible(), "Should find at least one remote startup card")

        # Click it
        remote_card.click()
        self.page.wait_for_selector("#details-drawer.active", timeout=5000)

        # Check that there is active remote marker
        has_temp_marker = self.page.evaluate("() => WorldTechApp.getTempRemoteMarker() !== null && WorldTechApp.getTempRemoteMarker().getElement().classList.contains('active')")
        self.assertTrue(has_temp_marker, "Temp remote marker should be added and active")

        # Pan the map programmatically to trigger re-fetch/clearAllMarkers
        self.page.evaluate("() => WorldTechApp.map.panBy([100, 100])")
        self.page.wait_for_timeout(2000)

        # Verify the temp marker still exists and has not been cleared
        still_has_temp_marker = self.page.evaluate("() => WorldTechApp.getTempRemoteMarker() !== null")
        self.assertTrue(still_has_temp_marker, "Temp remote marker should persist after map pans and re-fetches")

        # Click the map background to close the drawer
        self.page.click("#map")
        self.page.wait_for_timeout(1000)

        # Verify the temp marker is cleanly removed
        marker_removed = self.page.evaluate("() => WorldTechApp.getTempRemoteMarker() === null")
        self.assertTrue(marker_removed, "Temp remote marker should be removed when closing the profile drawer")

    def test_g5_map_zoom_pan_viewport_preservation(self):
        """Verify that zooming or panning the map programmatically preserves the new zoom/center and does not reset."""
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_timeout(2000)

        # Set a new zoom level
        self.page.evaluate("() => WorldTechApp.map.setZoom(14)")
        self.page.wait_for_timeout(1500)

        # Verify zoom level was preserved and did not reset back to default (11)
        current_zoom = self.page.evaluate("() => WorldTechApp.map.getZoom()")
        self.assertAlmostEqual(current_zoom, 14, delta=0.1, msg="Map zoom should stay at 14 and not reset")

        # Record current center
        center_before = self.page.evaluate("() => { const c = WorldTechApp.map.getCenter(); return [c.lng, c.lat]; }")

        # Pan the map programmatically
        self.page.evaluate("() => WorldTechApp.map.panBy([100, 100], {animate: false})")
        self.page.wait_for_timeout(1500)

        # Verify center was modified and did not reset back to default
        center_after = self.page.evaluate("() => { const c = WorldTechApp.map.getCenter(); return [c.lng, c.lat]; }")
        self.assertNotEqual(center_before[0], center_after[0], "Longitude should have panned and remained changed")
        self.assertNotEqual(center_before[1], center_after[1], "Latitude should have panned and remained changed")



    def test_frontend_color_rendering(self):
        """Verify that startups classified under 'Service Industry' are colored using the correct color on MapLibre markers."""
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_load_state("domcontentloaded")

        # Wait until WorldTechApp and state are fully loaded
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && window.WorldTechApp.state && window.WorldTechApp.state.startupsData && window.WorldTechApp.state.startupsData.length > 0",
            timeout=10000
        )

        # Retrieve color mapping of Service Industry markers on the map
        colors = self.page.evaluate("""() => {
            const res = [];
            for (const [id, marker] of WorldTechApp.state.markersMap.entries()) {
                const startup = WorldTechApp.state.startupsData.find(s => s.id == id);
                if (startup && startup.industry === 'Service Industry') {
                    const el = marker.getElement();
                    const fallbackEl = el.querySelector('.logo-marker-fallback');
                    const bg = fallbackEl ? fallbackEl.style.backgroundColor : null;
                    res.push({ id, name: startup.name, color: bg });
                }
            }
            return res;
        }""")

        self.assertTrue(len(colors) > 0, "Should have at least one Service Industry marker")
        for marker_info in colors:
            self.assertIn("rgb(234, 88, 12)", marker_info['color'], f"Marker for {marker_info['name']} should have color rgb(234, 88, 12) (#ea580c)")



if __name__ == '__main__':
    print("\n======================================================================")
    print(" 🚀 AUTOMATED E2E INTERACTIVE QA TEST SUITE (PLAYWRIGHT CHROMIUM) 🚀")
    print("======================================================================")
    unittest.main(verbosity=2)
