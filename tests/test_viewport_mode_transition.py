#!/usr/bin/env python3
"""
Viewport Mode Transition on Manual Pan (R2) Test Suite:
tests/test_viewport_mode_transition.py

Verifies:
1. Static code assertions on public/static/js/app.js
   ensuring they implement the R2 manual pan/zoom transition logic correctly.
2. Playwright E2E simulation (if available) verifying that searching a city (e.g. Bengaluru)
   and triggering a manual pan/zoom transitions UI and URL parameters to Viewport mode correctly.
"""

import unittest
import os
import sys
import json
import time
import threading
import urllib.request
import urllib.parse
import re

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app import app

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class TestViewportModeTransition(unittest.TestCase):
    """Test suite for Viewport Mode Transition on Manual Pan (R2) requirements."""

    BASE_URL = "http://127.0.0.1:5003"

    @classmethod
    def setUpClass(cls):
        """Manage backend server lifecycle and start Playwright headless Chromium for tests."""
        cls.server_thread = None
        cls.server = None
        cls.server_ready = False

        if PLAYWRIGHT_AVAILABLE:
            # Check if a backend server is already running on 5003
            try:
                with urllib.request.urlopen(f"{cls.BASE_URL}/api/companies?limit=1", timeout=1) as response:
                    if response.status == 200:
                        cls.server_ready = True
            except Exception:
                cls.server_ready = False

            if not cls.server_ready:
                from werkzeug.serving import make_server
                app.testing = True
                cls.server = make_server("127.0.0.1", 5003, app, threaded=True)
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
                print("Warning: Backend Flask server could not be started for Playwright E2E tests.")

            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch(headless=True)
        else:
            print("Playwright is not available. Skipping E2E browser tests.")

    @classmethod
    def tearDownClass(cls):
        """Shutdown the Flask server and browser if started by this suite."""
        if hasattr(cls, 'browser') and cls.browser:
            cls.browser.close()
        if hasattr(cls, 'playwright') and cls.playwright:
            cls.playwright.stop()
        if hasattr(cls, 'server') and cls.server:
            cls.server.shutdown()
            if hasattr(cls, 'server_thread') and cls.server_thread:
                cls.server_thread.join(timeout=2)

    def setUp(self):
        """Create a fresh browser context and page, and register offline CDN mocks for each test."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            return
        self.context = self.browser.new_context()
        self.page = self.context.new_page()

        # Setup route mocks for external CDNs to allow offline execution and speed up loading
        self.page.route(re.compile(r"https://cdn\.tailwindcss\.com.*"), lambda route: route.fulfill(
            status=200,
            content_type="text/javascript",
            body="window.tailwind = { config: {} };"
        ))
        self.page.route(re.compile(r"https://unpkg\.com/maplibre-gl@.*/dist/maplibre-gl\.js"), lambda route: route.fulfill(
            status=200,
            content_type="text/javascript",
            body="""
            window.maplibregl = {
                Map: function() {
                    this._listeners = {};
                    this._layers = {};
                    this._sources = {};
                    this.on = function(event, cb) {
                        this._listeners[event] = this._listeners[event] || [];
                        this._listeners[event].push(cb);
                        if (event === 'load' || event === 'style.load') {
                            setTimeout(cb, 10);
                        }
                        return this;
                    };
                    this.fire = function(event, data) {
                        const list = this._listeners[event] || [];
                        for (const cb of list) {
                            cb(data);
                        }
                        return this;
                    };
                    this.zoom = 11;
                    this.center = { lng: 77.5946, lat: 12.9716 };
                    this.addControl = function() { return this; };
                    this.getContainer = function() {
                        return { clientWidth: 1024, clientHeight: 768 };
                    };
                    this.getBounds = function() {
                        const span = 0.05 * Math.pow(2, 11 - this.zoom);
                        return {
                            getSouth: () => this.center.lat - span,
                            getNorth: () => this.center.lat + span,
                            getWest: () => this.center.lng - span,
                            getEast: () => this.center.lng + span,
                            _ne: { lat: this.center.lat + span, lng: this.center.lng + span },
                            _sw: { lat: this.center.lat - span, lng: this.center.lng - span }
                        };
                    };
                    this.flyTo = function(options) { return this; };
                    this.jumpTo = function(options) { if (options && options.center) this.center = options.center; return this; };
                    this.resize = function() { return this; };
                    this.getZoom = function() { return this.zoom; };
                    this.setZoom = function(z) { this.zoom = z; return this; };
                    this.panBy = function(offset, options) {
                        this.center.lng += 0.01;
                        this.center.lat += 0.01;
                        return this;
                    };
                    this.fitBounds = function(bounds, options) {
                        if (bounds && bounds.length === 2) {
                            const sw = bounds[0];
                            const ne = bounds[1];
                            this.center = { lng: (sw[0] + ne[0]) / 2, lat: (sw[1] + ne[1]) / 2 };
                        }
                        return this;
                    };
                    this.getSource = function(id) { return this._sources[id] || null; };
                    this.addSource = function(id, data) { this._sources[id] = { setData: (d) => { this._sources[id].data = d; } }; return this; };
                    this.getLayer = function(id) { return this._layers[id] || null; };
                    this.addLayer = function(layerObj) { this._layers[layerObj.id] = layerObj; return this; };
                    this.removeLayer = function(id) { delete this._layers[id]; return this; };
                    this.removeSource = function(id) { delete this._sources[id]; return this; };
                    this.setPaintProperty = function() { return this; };
                    this.getCenter = function() { return this.center; };
                    this.touchZoomRotate = { disableRotation: function() {} };
                },
                NavigationControl: function() {},
                Marker: function() {
                    const el = document.createElement('div');
                    el.className = 'logo-marker-container';
                    const fallbackEl = document.createElement('div');
                    fallbackEl.className = 'logo-marker-fallback';
                    fallbackEl.style.backgroundColor = 'rgb(234, 88, 12)';
                    el.appendChild(fallbackEl);
                    this.setLngLat = function() { return this; };
                    this.addTo = function() { return this; };
                    this.remove = function() { return this; };
                    this.getElement = function() { return el; };
                }
            };
            """
        ))
        self.page.route(re.compile(r"https://cdnjs\.cloudflare\.com/ajax/libs/font-awesome/.*"), lambda route: route.fulfill(status=200, content_type="text/css", body=""))
        self.page.route(re.compile(r"https://unpkg\.com/maplibre-gl@.*/dist/maplibre-gl\.css"), lambda route: route.fulfill(status=200, content_type="text/css", body=""))
        self.page.route(re.compile(r"https://fonts\.googleapis\.com/.*"), lambda route: route.fulfill(status=200, content_type="text/css", body=""))
        self.page.route(re.compile(r"https://fonts\.gstatic\.com/.*"), lambda route: route.fulfill(status=200, content_type="text/css", body=""))
        self.page.route(re.compile(r"https://.*\.basemaps\.cartocdn\.com/.*"), lambda route: route.fulfill(status=200, content_type="application/json", body="{}"))
        self.page.route(re.compile(r"https://tiles\.basemaps\.cartocdn\.com/.*"), lambda route: route.fulfill(status=200, content_type="application/json", body="{}"))

        # Setup route mock for Nominatim geocoding
        def handle_nominatim(route):
            url = route.request.url
            parsed = urllib.parse.urlparse(url)
            query = urllib.parse.parse_qs(parsed.query).get('q', [''])[0]
            
            mocks = {
                "bengaluru": {
                    "lat": "12.9716", "lon": "77.5946",
                    "boundingbox": ["12.8716", "13.0716", "77.4946", "77.6946"]
                },
                "mumbai": {
                    "lat": "19.0760", "lon": "72.8777",
                    "boundingbox": ["18.9760", "19.1760", "72.7777", "72.9777"]
                },
                "delhi": {
                    "lat": "28.6139", "lon": "77.2090",
                    "boundingbox": ["28.5139", "28.7139", "77.1090", "77.3090"]
                },
                "london": {
                    "lat": "51.5074", "lon": "-0.1278",
                    "boundingbox": ["51.4074", "51.6074", "-0.2278", "-0.0278"]
                },
                "usa": {
                    "lat": "37.7749", "lon": "-122.4194",
                    "boundingbox": ["37.6749", "37.8749", "-122.5194", "-122.3194"]
                },
                "indiranagar": {
                    "lat": "12.9732913", "lon": "77.6404672",
                    "boundingbox": ["12.9532913", "12.9932913", "77.6204672", "77.6604672"]
                }
            }
            
            matched_key = None
            for key in mocks:
                if key in query.lower():
                    matched_key = key
                    break
            
            if matched_key:
                m = mocks[matched_key]
                body = [{
                    "importance": 0.5,
                    "type": "city",
                    "class": "place",
                    "lat": m["lat"],
                    "lon": m["lon"],
                    "boundingbox": m["boundingbox"],
                    "geojson": {
                        "type": "Polygon",
                        "coordinates": [[[float(m["boundingbox"][2]), float(m["boundingbox"][0])],
                                         [float(m["boundingbox"][3]), float(m["boundingbox"][0])],
                                         [float(m["boundingbox"][3]), float(m["boundingbox"][1])],
                                         [float(m["boundingbox"][2]), float(m["boundingbox"][1])],
                                         [float(m["boundingbox"][2]), float(m["boundingbox"][0])]]]
                    }
                }]
                route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
            else:
                route.fulfill(status=200, content_type="application/json", body="[]")

        self.page.route(re.compile(r"https://nominatim\.openstreetmap\.org/search.*"), handle_nominatim)

    def tearDown(self):
        """Close browser page and context after test."""
        if hasattr(self, 'page') and self.page:
            self.page.close()
        if hasattr(self, 'context') and self.context:
            self.context.close()



    def test_static_code_assertions_public_app_js(self):
        """Assert that public/static/js/app.js correctly implements the manual pan/zoom transition logic."""
        app_js_path = os.path.join(PROJECT_ROOT, "public/static/js/app.js")
        self.assertTrue(os.path.exists(app_js_path), f"File {app_js_path} does not exist.")
        self._verify_static_rules(app_js_path)

    def _verify_static_rules(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check map.on('moveend') is registered
        self.assertIn("map.on('moveend'", content, "map.on('moveend') handler registration is missing")

        # Normalize spaces/newlines inside map.on('moveend') block to check for state resets
        # Find moveend block contents
        moveend_match = re.search(r"map\.on\('moveend',\s*\(e\)\s*=>\s*({.*?\},\s*300\);\s*\}\);?)", content, re.DOTALL)
        self.assertIsNotNone(moveend_match, "Could not locate map.on('moveend') handler body")
        handler_body = moveend_match.group(1)

        # 1. Resetting state.searchedCity
        self.assertTrue(
            re.search(r"state\.searchedCity\s*=\s*['\"]['\"];?", handler_body),
            "state.searchedCity reset is missing in moveend handler"
        )

        # 2. Resetting state.boundsOverride
        self.assertTrue(
            re.search(r"state\.boundsOverride\s*=\s*null;?", handler_body),
            "state.boundsOverride reset is missing in moveend handler"
        )

        # 3. Assert clearSearchBoundary() is NOT called in moveend handler
        self.assertNotIn(
            "clearSearchBoundary()",
            handler_body,
            "clearSearchBoundary() call should not be present in moveend handler"
        )

        # 4. Deleting 'city' query parameter and replacing browser history state
        self.assertTrue(
            "new URLSearchParams(window.location.search)" in handler_body or
            "new URLSearchParams(location.search)" in handler_body,
            "URLSearchParams usage is missing in moveend handler"
        )
        self.assertTrue(
            "urlParams.delete('city')" in handler_body or
            "urlParams.delete(\"city\")" in handler_body,
            "urlParams.delete('city') is missing in moveend handler"
        )
        self.assertTrue(
            "history.replaceState" in handler_body or
            "window.history.replaceState" in handler_body,
            "window.history.replaceState is missing in moveend handler"
        )

        # 5. Resetting #activeMapTitle to 'All locations'
        self.assertTrue(
            "activeMapTitle" in handler_body,
            "#activeMapTitle reference is missing in moveend handler"
        )
        self.assertTrue(
            re.search(r"['\"]All locations['\"]", handler_body),
            "Setting text content to 'All locations' is missing in moveend handler"
        )

        # 6. Clearing #unified-search-input value and placeholder
        self.assertTrue(
            "unified-search-input" in handler_body,
            "#unified-search-input reference is missing in moveend handler"
        )
        self.assertTrue(
            re.search(r"placeholder\s*=\s*['\"]Search city/location \.\.\.['\"]", handler_body),
            "Setting placeholder to 'Search city/location ...' is missing in moveend handler"
        )
        self.assertTrue(
            re.search(r"value\s*=\s*['\"]['\"]", handler_body),
            "Clearing search input value is missing in moveend handler"
        )

    def test_playwright_viewport_mode_transition_on_pan(self):
        """E2E Test: Simulate search followed by manual pan/zoom to verify transition to Viewport mode."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        # 1. Load Homepage
        self.page.goto(f"{self.BASE_URL}/")
        self.page.wait_for_load_state("domcontentloaded")

        # 2. Click preset search button (e.g. Bengaluru)
        self.page.click("button[onclick=\"handlePresetSearch('bengaluru')\"]")
        
        # Wait for redirect to /jobs
        self.page.wait_for_url("**/jobs?city=Bengaluru%2C%20KA")
        self.page.wait_for_load_state("domcontentloaded")

        # 3. Wait for WorldTechApp, state, and map to be initialized robustly
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && "
            "window.WorldTechApp.state && "
            "window.WorldTechApp.map && "
            "window.WorldTechApp.state.startupsData && "
            "window.WorldTechApp.state.startupsData.length > 0 && "
            "!window.WorldTechApp.state.isProgrammaticMove",
            timeout=15000
        )

        # Confirm initial state is in City search mode
        self.assertEqual(
            self.page.evaluate("() => window.WorldTechApp.state.searchedCity").lower(),
            "bengaluru, ka"
        )
        self.assertEqual(
            self.page.locator("#activeMapTitle").text_content().strip().lower(),
            "bengaluru, ka"
        )

        # Confirm search input retains query value after search (R4)
        initial_input_val = self.page.locator("#unified-search-input").input_value()
        self.assertIn("Bengaluru", initial_input_val, f"Search input should retain query value 'Bengaluru'. Got: {initial_input_val}")

        # Confirm boundary layer exists before pan (R3)
        self.page.wait_for_function("() => !!window.WorldTechApp.map.getLayer('search-boundary-outline')", timeout=5000)
        has_layer_before = self.page.evaluate("() => !!window.WorldTechApp.map.getLayer('search-boundary-outline')")
        self.assertTrue(has_layer_before, "Search boundary outline layer should be visible before pan")

        # Set search input value and placeholder to mock custom filter state
        self.page.evaluate("""() => {
            const navInput = document.getElementById('unified-search-input');
            if (navInput) {
                navInput.value = 'React';
                navInput.placeholder = 'Search React...';
            }
        }""")

        # 4. Trigger manual map move. We simulate this programmatically by firing
        # the 'moveend' event with an originalEvent property set (simulating user pan).
        # This bypasses the programmatic move check.
        self.page.evaluate("window.WorldTechApp.map.fire('moveend', { originalEvent: {} })")

        # Wait robustly for the transition to Viewport mode (url query param city deleted)
        self.page.wait_for_function("() => !window.location.search.includes('city=')", timeout=5000)

        # 5. Verify the transition to Viewport mode
        # URL must not contain city param anymore
        current_url = self.page.url
        self.assertNotIn("city=", current_url, f"City query param should be deleted from URL. Current URL: {current_url}")

        # state.searchedCity must be empty
        searched_city = self.page.evaluate("() => window.WorldTechApp.state.searchedCity")
        self.assertEqual(searched_city, "", "state.searchedCity should be cleared")

        # state.boundsOverride must be null
        bounds_override = self.page.evaluate("() => window.WorldTechApp.state.boundsOverride")
        self.assertIsNone(bounds_override, "state.boundsOverride should be null")

        # activeMapTitle must be reset to "All locations"
        title_text = self.page.locator("#activeMapTitle").text_content().strip()
        self.assertEqual(title_text, "All locations", "Active map title should be reset to 'All locations'")

        # Confirm boundary layer remains visible after pan (R3)
        has_layer_after = self.page.evaluate("() => !!window.WorldTechApp.map.getLayer('search-boundary-outline')")
        self.assertTrue(has_layer_after, "Search boundary outline layer should remain visible after pan")

        # unified-search-input must be cleared and placeholder reset
        input_val = self.page.locator("#unified-search-input").input_value()
        input_placeholder = self.page.locator("#unified-search-input").get_attribute("placeholder")
        self.assertEqual(input_val, "", "Search input value should be cleared")
        self.assertEqual(input_placeholder, "Search city/location ...", "Search input placeholder should be reset")

    def test_local_zoom_unpinned_exclusion(self):
        """Backend Unit Test: Verify filter_and_sort_startups unpinned exclusion based on lat_span."""
        from backend.services.startup_service import filter_and_sort_startups

        mock_startups = [
            {"id": 1, "name": "Pinned In-Bounds", "lat": 12.7, "lng": 77.6, "has_pin": True},
            {"id": 2, "name": "Pinned Out-of-Bounds", "lat": 14.0, "lng": 77.6, "has_pin": True},
            {"id": 3, "name": "Unpinned Startup", "lat": None, "lng": None, "has_pin": False}
        ]

        # Case 1: lat_span < 1.0 (min_lat=12.5, max_lat=13.0) -> Unpinned must be excluded
        result_local = filter_and_sort_startups(
            mock_startups,
            min_lat=12.5, max_lat=13.0,
            min_lng=77.0, max_lng=78.0,
            limit=-1
        )
        self.assertEqual(len(result_local), 1)
        self.assertEqual(result_local[0]["id"], 1)

        # Case 2: lat_span >= 1.0 (min_lat=11.5, max_lat=13.0) -> Unpinned must be preserved
        result_wide = filter_and_sort_startups(
            mock_startups,
            min_lat=11.5, max_lat=13.0,
            min_lng=77.0, max_lng=78.0,
            limit=-1
        )
        self.assertEqual(len(result_wide), 2)
        ids = {s["id"] for s in result_wide}
        self.assertIn(1, ids)
        self.assertIn(3, ids)

        # Case 3: No bounding box -> Unpinned must be preserved
        result_no_bbox = filter_and_sort_startups(
            mock_startups,
            min_lat=None, max_lat=None,
            min_lng=None, max_lng=None,
            limit=-1
        )
        self.assertEqual(len(result_no_bbox), 3)

    def test_playwright_initial_load_empty_sidebar(self):
        """E2E Test: Load /jobs directly without city, assert empty sidebar text, no markers, no api call."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        api_calls = []
        def handle_request(request):
            if "/api/companies" in request.url:
                api_calls.append(request.url)

        self.page.on("request", handle_request)

        self.page.goto(f"{self.BASE_URL}/jobs")
        self.page.wait_for_load_state("domcontentloaded")

        # Wait for WorldTechApp to be defined
        self.page.wait_for_function("() => typeof window.WorldTechApp !== 'undefined'")

        # Verify sidebar empty text
        sidebar_text = self.page.locator("#directory-list").text_content()
        self.assertIn(
            "Search for a city or location to find companies and jobs.",
            sidebar_text
        )

        # Verify no markers are displayed
        markers_count = self.page.evaluate("() => window.WorldTechApp.state.markersMap.size")
        self.assertEqual(markers_count, 0)

        # Verify no API requests to /api/companies
        self.assertEqual(len(api_calls), 0)

    def test_playwright_viewport_pan_sidebar_update(self):
        """E2E Test: Search Bengaluru, pan map manually, verify sidebar directory updates to bounds."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        self.page.goto(f"{self.BASE_URL}/")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.click("button[onclick=\"handlePresetSearch('bengaluru')\"]")
        self.page.wait_for_url("**/jobs?city=Bengaluru%2C%20KA")

        # Wait robustly for WorldTechApp and startups to load and programmatic move lock to release
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && "
            "window.WorldTechApp.state && "
            "window.WorldTechApp.state.startupsData && "
            "window.WorldTechApp.state.startupsData.length > 0 && "
            "!window.WorldTechApp.state.isProgrammaticMove",
            timeout=15000
        )

        self.page.wait_for_selector(".directory-item")
        initial_companies = self.page.eval_on_selector_all(".directory-item .card-title", "elements => elements.map(el => el.textContent.trim())")
        self.assertTrue(len(initial_companies) > 0, "Should load initial companies in Bengaluru")

        # Simulate manual map pan programmatically
        self.page.evaluate("""() => {
            const center = window.WorldTechApp.map.getCenter();
            window.WorldTechApp.map.center = { lng: center.lng + 0.1, lat: center.lat + 0.1 };
            window.WorldTechApp.map.fire('moveend', { originalEvent: {} });
        }""")

        # Wait for the transition to Viewport mode
        self.page.wait_for_function("() => !window.location.search.includes('city=')", timeout=5000)

        # Wait a small bit for rendering to finish
        self.page.wait_for_timeout(1000)

        panned_companies = self.page.eval_on_selector_all(".directory-item .card-title", "elements => elements.map(el => el.textContent.trim())")
        self.assertNotEqual(initial_companies, panned_companies, "Company list should have changed after manual panning")

    def test_playwright_indiranagar_clean_search(self):
        """E2E Test: Search Indiranagar and verify only Indiranagar physical startups are returned (unpinned/remote excluded)."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        # Load /jobs directly where the navbar search is always visible
        self.page.goto(f"{self.BASE_URL}/jobs")
        self.page.wait_for_load_state("domcontentloaded")

        # Wait for WorldTechApp to load
        self.page.wait_for_function("() => typeof window.WorldTechApp !== 'undefined'")

        self.page.fill("#unified-search-input", "Indiranagar")
        self.page.press("#unified-search-input", "Enter")

        self.page.wait_for_url("**/jobs?city=Indiranagar*")

        # Wait for geocoding / search bounds request to complete and state to update
        self.page.wait_for_function(
            "() => window.WorldTechApp.state && "
            "window.WorldTechApp.state.startupsData && "
            "window.WorldTechApp.state.startupsData.length > 0"
        )

        self.page.wait_for_selector(".directory-item")
        company_names = self.page.eval_on_selector_all(".directory-item .card-title", "elements => elements.map(el => el.textContent.trim())")

        # "Indira Pay" and "Zenith SaaS" must be present (physically located in Indiranagar)
        self.assertIn("Indira Pay", company_names)
        self.assertIn("Zenith SaaS", company_names)

        # "BairesDev" (remote startup) must be excluded
        self.assertNotIn("BairesDev", company_names)

    def test_playwright_non_hub_search_and_pan(self):
        """E2E Test: Search non-hub city (Delhi), fly there, pan, and verify transition to Viewport mode."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        self.page.goto(f"{self.BASE_URL}/jobs")
        self.page.wait_for_load_state("domcontentloaded")

        # Wait for WorldTechApp to load
        self.page.wait_for_function("() => typeof window.WorldTechApp !== 'undefined'")

        # Type Delhi in unified search and enter
        self.page.fill("#unified-search-input", "Delhi")
        self.page.press("#unified-search-input", "Enter")

        self.page.wait_for_url("**/jobs?city=Delhi*")
        self.page.wait_for_load_state("domcontentloaded")

        # Wait robustly for map to fly to Delhi and programmatic move to clear
        self.page.wait_for_function(
            "() => window.WorldTechApp.state && "
            "window.WorldTechApp.state.searchedCity === 'delhi' && "
            "!window.WorldTechApp.state.isProgrammaticMove",
            timeout=15000
        )

        # Confirm title displays Delhi
        self.assertEqual(
            self.page.locator("#activeMapTitle").text_content().strip(),
            "Delhi"
        )

        # Confirm boundary layer exists before pan
        has_layer_before = self.page.evaluate("() => !!window.WorldTechApp.map.getLayer('search-boundary-outline')")
        self.assertTrue(has_layer_before, "Search boundary outline layer should be visible before pan")

        # Trigger manual map move (simulated via fire moveend with originalEvent)
        self.page.evaluate("window.WorldTechApp.map.fire('moveend', { originalEvent: {} })")

        # Wait for transition to Viewport mode
        self.page.wait_for_function("() => !window.location.search.includes('city=')", timeout=5000)

        # Verify transition to Viewport mode
        current_url = self.page.url
        self.assertNotIn("city=", current_url, "City query param should be deleted from URL")

        searched_city = self.page.evaluate("() => window.WorldTechApp.state.searchedCity")
        self.assertEqual(searched_city, "", "state.searchedCity should be cleared")

        title_text = self.page.locator("#activeMapTitle").text_content().strip()
        self.assertEqual(title_text, "All locations", "Active map title should be reset to 'All locations'")

        # Confirm boundary layer remains visible after pan (R3)
        has_layer_after = self.page.evaluate("() => !!window.WorldTechApp.map.getLayer('search-boundary-outline')")
        self.assertTrue(has_layer_after, "Search boundary outline layer should remain visible after pan")

        input_val = self.page.locator("#unified-search-input").input_value()
        self.assertEqual(input_val, "", "Search input value should be cleared")

    def test_playwright_whitespace_search_handling(self):
        """E2E Test: Verify that whitespace-only search does not trigger geocoding or state changes."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        # Record if a fetch to Nominatim is initiated
        nominatim_called = []
        def handle_route(route):
            nominatim_called.append(route.request.url)
            route.fulfill(status=200, body="[]")

        self.page.route("https://nominatim.openstreetmap.org/**", handle_route)

        self.page.goto(f"{self.BASE_URL}/jobs")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_function("() => typeof window.WorldTechApp !== 'undefined'")

        # Fill search input with spaces and press enter
        self.page.fill("#unified-search-input", "   ")
        self.page.press("#unified-search-input", "Enter")

        self.page.wait_for_timeout(1000)

        # Verify Nominatim was NOT called
        self.assertEqual(len(nominatim_called), 0, f"Nominatim should not be called for whitespace queries. Calls: {nominatim_called}")

        # Verify input is still spaces or empty, and no transition or change in search modes occurred
        searched_city = self.page.evaluate("() => window.WorldTechApp.state.searchedCity")
        self.assertEqual(searched_city, "", "Searched city should remain empty")


if __name__ == '__main__':
    unittest.main()

