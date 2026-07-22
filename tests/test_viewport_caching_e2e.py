#!/usr/bin/env python3
"""
E2E Playwright verification suite for Viewport Caching & Filtering:
tests/test_viewport_caching_e2e.py
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


class TestViewportCachingE2E(unittest.TestCase):
    """E2E Test suite for Viewport Caching containment and filtering optimization."""

    BASE_URL = "http://127.0.0.1:5009"

    @classmethod
    def setUpClass(cls):
        """Manage backend server lifecycle and start Playwright headless Chromium for tests."""
        cls.server_thread = None
        cls.server = None
        cls.server_ready = False

        if PLAYWRIGHT_AVAILABLE:
            # Check if a backend server is already running on 5009
            try:
                with urllib.request.urlopen(f"{cls.BASE_URL}/api/companies?limit=1", timeout=1) as response:
                    if response.status == 200:
                        cls.server_ready = True
            except Exception:
                cls.server_ready = False

            if not cls.server_ready:
                from werkzeug.serving import make_server
                app.testing = True
                cls.server = make_server("127.0.0.1", 5009, app, threaded=True)
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
        # Explicitly set desktop viewport size to ensure UI layout consistency
        self.page.set_viewport_size({"width": 1280, "height": 800})
        self.page.on("console", lambda msg: print(f"[CONSOLE] {msg.text}"))
        self.js_errors = []
        self.page.on("pageerror", lambda err: self.js_errors.append(err))

        # Setup route mocks for external CDNs to allow offline execution and speed up loading
        tailwind_mock_js = """
        window.tailwind = { config: {} };
        const style = document.createElement('style');
        style.textContent = `
            #app-container {
                position: absolute !important;
                top: 0 !important;
                right: 0 !important;
                bottom: 0 !important;
                left: 0 !important;
                z-index: 30 !important;
                display: flex !important;
                flex-direction: column !important;
                height: 100% !important;
                width: 100% !important;
                background-color: #ffffff !important;
            }
            .content-wrapper {
                flex: 1 1 0% !important;
                display: flex !important;
                overflow: hidden !important;
                position: relative !important;
            }
        `;
        document.head.appendChild(style);
        """
        self.page.route(re.compile(r"https://cdn\.tailwindcss\.com.*"), lambda route: route.fulfill(
            status=200,
            content_type="text/javascript",
            body=tailwind_mock_js
        ))
        self.page.route(re.compile(r"https://unpkg\.com/maplibre-gl@.*/dist/maplibre-gl\.js"), lambda route: route.fulfill(
            status=200,
            content_type="text/javascript",
            body="""
            window.maplibregl = {
                Map: function() {
                    const self = this;
                    this._listeners = {};
                    this._layers = {};
                    this._sources = {};
                    this.zoom = 11;
                    this.center = { lng: 77.5946, lat: 12.9716 };

                    this.on = function(event, cb) {
                        self._listeners[event] = self._listeners[event] || [];
                        self._listeners[event].push(cb);
                        if (event === 'load' || event === 'style.load') {
                            setTimeout(cb, 10);
                        }
                        return this;
                    };

                    this.fire = function(event, data) {
                        const list = self._listeners[event] || [];
                        for (const cb of list) {
                            cb(data);
                        }
                        return this;
                    };

                    // Listen to DOM clicks on map container to trigger Maplibre click events
                    setTimeout(() => {
                        const mapEl = document.getElementById('map');
                        if (mapEl) {
                            mapEl.addEventListener('click', (e) => {
                                if (e.target.closest('.logo-marker-container')) return;
                                self.fire('click', {
                                    lngLat: self.getCenter(),
                                    point: { x: e.clientX, y: e.clientY },
                                    originalEvent: e
                                });
                            });
                        }
                    }, 100);

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
                    this.flyTo = function(options) {
                        if (options && options.center) this.center = options.center;
                        if (options && options.zoom !== undefined) this.zoom = options.zoom;
                        self.fire('moveend');
                        return this;
                    };
                    this.jumpTo = function(options) {
                        if (options && options.center) this.center = options.center;
                        if (options && options.zoom !== undefined) this.zoom = options.zoom;
                        self.fire('moveend');
                        return this;
                    };
                    this.resize = function() { return this; };
                    this.getZoom = function() { return this.zoom; };
                    this.setZoom = function(z) {
                        this.zoom = z;
                        self.fire('moveend');
                        return this;
                    };
                    this.panBy = function(offset, options) {
                        this.center.lng += 0.01;
                        this.center.lat += 0.01;
                        self.fire('moveend');
                        return this;
                    };
                    this.fitBounds = function(bounds, options) {
                        if (bounds && bounds.length === 2) {
                            const sw = bounds[0];
                            const ne = bounds[1];
                            this.center = { lng: (sw[0] + ne[0]) / 2, lat: (sw[1] + ne[1]) / 2 };
                        }
                        self.fire('moveend');
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
                    this.addTo = function(map) {
                        const mapContainer = document.getElementById('map') || document.body;
                        mapContainer.appendChild(el);
                        return this;
                    };
                    this.remove = function() {
                        if (el.parentNode) {
                            el.parentNode.removeChild(el);
                        }
                        return this;
                    };
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
        """Close browser page and context and assert zero JS errors."""
        if hasattr(self, 'page') and self.page:
            self.page.close()
        if hasattr(self, 'context') and self.context:
            self.context.close()
        if hasattr(self, 'js_errors'):
            self.assertEqual(self.js_errors, [], f"JS runtime errors captured: {self.js_errors}")

    def test_e2e_viewport_zoom_in_cache_hit(self):
        """Verify that zooming in (subset viewport) after a pan (bounded query) does NOT trigger a new API request."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        # Track network requests to /api/companies
        api_requests = []
        def handle_request(request):
            if "/api/companies" in request.url:
                api_requests.append(request.url)

        self.page.on("request", handle_request)

        # 1. Load Homepage and search Bengaluru (Initial load, city query)
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru")
        self.page.wait_for_load_state("domcontentloaded")

        # Wait for map and initial data load
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && "
            "window.WorldTechApp.state && "
            "window.WorldTechApp.state.startupsData && "
            "window.WorldTechApp.state.startupsData.length > 0 && "
            "!window.WorldTechApp.state.isProgrammaticMove",
            timeout=15000
        )

        self.assertEqual(len(api_requests), 1, "Expected exactly 1 API request on initial load")
        
        # 2. Pan the map slightly to trigger a bounded query (Request 2)
        self.page.evaluate("""() => {
            const center = window.WorldTechApp.map.getCenter();
            // Shift center slightly to trigger moveend and bounded query
            window.WorldTechApp.map.center = { lng: center.lng + 0.02, lat: center.lat + 0.02 };
            window.WorldTechApp.map.fire('moveend', { originalEvent: {} });
        }""")

        # Wait for debounce and fetch to complete
        self.page.wait_for_timeout(1500)

        # Verify Request 2 was made (total should be 2)
        self.assertEqual(len(api_requests), 2, f"Panning should trigger a new API request. Requests: {api_requests}")
        
        # Get the bounds after pan (this will be the "outer" cached bounds)
        panned_bounds = self.page.evaluate("window.WorldTechApp.map.getBounds()")
        panned_count = len(self.page.locator(".directory-item").all())

        # 3. Simulate Zoom In (Programmatically shrink bounds inside the panned area)
        ne_lat = panned_bounds["_ne"]["lat"]
        ne_lng = panned_bounds["_ne"]["lng"]
        sw_lat = panned_bounds["_sw"]["lat"]
        sw_lng = panned_bounds["_sw"]["lng"]

        # Shrink bounds delta (which fits inside the outer cached bounds)
        # Zoom in programmatically by setting map zoom larger
        self.page.evaluate("""() => {
            const z = window.WorldTechApp.map.getZoom();
            window.WorldTechApp.map.setZoom(z + 1);
            window.WorldTechApp.map.fire('moveend', { originalEvent: {} });
        }""")

        # Wait for debounce
        self.page.wait_for_timeout(1000)

        # Verify NO new API request was made (total should still be 2)
        self.assertEqual(len(api_requests), 2, f"Zooming in should NOT trigger a new API request (should hit cache). Requests: {api_requests}")

        # Verify directory updated (should have fewer or equal startups than panned state)
        zoom_in_count = len(self.page.locator(".directory-item").all())
        self.assertTrue(zoom_in_count <= panned_count, f"Expected fewer or equal startups after zoom in. Panned: {panned_count}, Zoomed: {zoom_in_count}")

    def test_e2e_viewport_pan_cache_miss(self):
        """Verify that panning (shifting viewport) DOES trigger a new API request."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        api_requests = []
        def handle_request(request):
            if "/api/companies" in request.url:
                api_requests.append(request.url)

        self.page.on("request", handle_request)

        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && "
            "window.WorldTechApp.state.startupsData.length > 0",
            timeout=15000
        )

        self.assertEqual(len(api_requests), 1)

        # Shift bounds to the east (pan right) by a significant amount (1.0 degree longitude)
        self.page.evaluate("""() => {
            const center = window.WorldTechApp.map.getCenter();
            window.WorldTechApp.map.center = { lng: center.lng + 1.0, lat: center.lat };
            window.WorldTechApp.map.fire('moveend', { originalEvent: {} });
        }""")

        # Wait for debounce and fetch
        self.page.wait_for_timeout(1000)

        # Verify a new API request WAS made (count should be 2)
        self.assertEqual(len(api_requests), 2, f"Panning should trigger a new API request. Requests: {api_requests}")

    def test_e2e_viewport_zoom_out_cache_miss(self):
        """Verify that zooming out (larger viewport) DOES trigger a new API request."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        api_requests = []
        def handle_request(request):
            if "/api/companies" in request.url:
                api_requests.append(request.url)

        self.page.on("request", handle_request)

        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && "
            "window.WorldTechApp.state.startupsData.length > 0",
            timeout=15000
        )

        self.assertEqual(len(api_requests), 1)

        # Zoom out programmatically by 2 levels (decreases zoom -> increases bounds span -> cache miss)
        self.page.evaluate("""() => {
            const zoom = window.WorldTechApp.map.getZoom();
            window.WorldTechApp.map.setZoom(zoom - 2);
            window.WorldTechApp.map.fire('moveend', { originalEvent: {} });
        }""")

        # Wait for debounce and fetch
        self.page.wait_for_timeout(1000)

        # Verify a new API request WAS made (count should be 2)
        self.assertEqual(len(api_requests), 2, f"Zooming out should trigger a new API request. Requests: {api_requests}")

    def test_e2e_filter_change_cache_miss(self):
        """Verify that changing any dropdown filter (e.g. work type, experience, salary) triggers a new API request."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        api_requests = []
        def handle_request(request):
            if "/api/companies" in request.url:
                api_requests.append(request.url)

        self.page.on("request", handle_request)

        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && "
            "window.WorldTechApp.state.startupsData.length > 0",
            timeout=15000
        )

        self.assertEqual(len(api_requests), 1, "Expected exactly 1 request on page load")

        # Select work type "remote"
        self.page.select_option("#filter-work-type", "remote")

        # Wait for request to dispatch and complete
        self.page.wait_for_timeout(1000)

        self.assertEqual(len(api_requests), 2, f"Changing work type filter should trigger a new API request. Requests: {api_requests}")
        self.assertIn("work_type=remote", api_requests[-1], "New request URL should contain work_type=remote parameter")

        # Select experience level "entry" (0-2 yrs)
        self.page.select_option("#filter-exp-level", "entry")

        # Wait for request
        self.page.wait_for_timeout(1000)

        self.assertEqual(len(api_requests), 3, f"Changing experience level filter should trigger a new API request. Requests: {api_requests}")
        self.assertIn("exp_level=entry", api_requests[-1], "New request URL should contain exp_level=entry parameter")

        # Select salary min 10
        self.page.select_option("#filter-salary-min", "10")

        # Wait for request
        self.page.wait_for_timeout(1000)

        self.assertEqual(len(api_requests), 4, f"Changing salary filter should trigger a new API request. Requests: {api_requests}")
        self.assertIn("salary_min=10", api_requests[-1], "New request URL should contain salary_min=10 parameter")

    def test_e2e_search_query_cache_miss(self):
        """Verify that searching a keyword/job role triggers a new API request even if viewport is unchanged."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        api_requests = []
        def handle_request(request):
            if "/api/companies" in request.url:
                api_requests.append(request.url)

        self.page.on("request", handle_request)

        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && "
            "window.WorldTechApp.state.startupsData.length > 0",
            timeout=15000
        )

        self.assertEqual(len(api_requests), 1, "Expected exactly 1 request on page load")

        # Fill search input with a job query role e.g. "Engineer" and press Enter to trigger executeUnifiedSearch
        self.page.fill("#unified-search-input", "Engineer")
        self.page.press("#unified-search-input", "Enter")

        # Wait for request to dispatch and complete
        self.page.wait_for_timeout(1000)

        self.assertEqual(len(api_requests), 2, f"Executing a role search should trigger a new API request. Requests: {api_requests}")
        self.assertIn("search=Engineer", api_requests[-1], "New request URL should contain search=Engineer parameter")

    def test_e2e_viewport_zoom_out_cache_hit(self):
        """Verify that zooming out (larger viewport) within a previously cached area does NOT trigger a new API request."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        api_requests = []
        def handle_request(request):
            if "/api/companies" in request.url:
                api_requests.append(request.url)

        self.page.on("request", handle_request)

        # 1. Load Homepage and search Bengaluru (Initial load, city query)
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && "
            "window.WorldTechApp.state && "
            "window.WorldTechApp.state.startupsData && "
            "window.WorldTechApp.state.startupsData.length > 0 && "
            "!window.WorldTechApp.state.isProgrammaticMove",
            timeout=15000
        )

        self.assertEqual(len(api_requests), 1, "Expected exactly 1 request on initial load")

        # 2. Pan map slightly to trigger bounded query (Request 2)
        self.page.evaluate("""() => {
            const center = window.WorldTechApp.map.getCenter();
            window.WorldTechApp.map.center = { lng: center.lng + 0.02, lat: center.lat + 0.02 };
            window.WorldTechApp.map.fire('moveend', { originalEvent: {} });
        }""")
        self.page.wait_for_timeout(1500)

        self.assertEqual(len(api_requests), 2, f"Panning should trigger request 2. Requests: {api_requests}")

        # Record bounds at panned state (the "outer" cached bounds)
        panned_count = len(self.page.locator(".directory-item").all())

        # 3. Zoom in (Request should hit cache)
        self.page.evaluate("""() => {
            const z = window.WorldTechApp.map.getZoom();
            window.WorldTechApp.map.setZoom(z + 1);
            window.WorldTechApp.map.fire('moveend', { originalEvent: {} });
        }""")
        self.page.wait_for_timeout(1000)

        # Verify no new request (still 2 requests)
        self.assertEqual(len(api_requests), 2, "Zooming in should hit the cache")

        # 4. Zoom out back to original panned zoom level (Request should hit cache because new bounds are within the outer cached bounds)
        self.page.evaluate("""() => {
            const z = window.WorldTechApp.map.getZoom();
            window.WorldTechApp.map.setZoom(z - 1);
            window.WorldTechApp.map.fire('moveend', { originalEvent: {} });
        }""")
        self.page.wait_for_timeout(1000)

        # Verify no new request (still 2 requests!)
        self.assertEqual(len(api_requests), 2, f"Zooming out within cached bounds should NOT trigger a new API request. Requests: {api_requests}")

    def test_e2e_data_versioning_handshake(self):
        """Verify that a backend data version change invalidates client-side cache and forces a new API request."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        api_requests = []
        def handle_request(request):
            if "/api/companies" in request.url:
                api_requests.append(request.url)

        self.page.on("request", handle_request)

        # 1. Initial load
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && "
            "window.WorldTechApp.state.startupsData.length > 0",
            timeout=15000
        )

        self.assertEqual(len(api_requests), 1, "Expected exactly 1 request on initial load")

        # 2. Modify dataset version on backend by touching startups.json
        from backend.services.startup_service import DATA_FILE
        original_mtime = os.path.getmtime(DATA_FILE)
        # Update mtime by adding 5 seconds (or setting to now)
        try:
            os.utime(DATA_FILE, (original_mtime + 5, original_mtime + 5))
        except Exception as e:
            self.skipTest(f"Unable to touch startups.json: {e}")

        try:
            # 3. Perform a request that will trigger a cache miss to get the new version from response headers
            # Let's change work type filter to 'remote'
            self.page.select_option("#filter-work-type", "remote")
            self.page.wait_for_timeout(1500)
            self.assertEqual(len(api_requests), 2, "Expected a new API request for filter change")

            # At this point, the client should have detected the new version and cleared the cache.
            # 4. Now reset the filter back to empty (all work types).
            # This would normally hit the cache for the original query (Bengaluru with no work type filter).
            # But since cache was cleared, it MUST result in a new API request to the backend.
            self.page.select_option("#filter-work-type", "")
            self.page.wait_for_timeout(1500)

            # If cache invalidation was successful, the total request count should be 3.
            # If cache invalidation failed, it would reuse the cached Bengaluru result and remain 2.
            self.assertEqual(len(api_requests), 3, f"Cache should have been cleared on version mismatch. Requests: {api_requests}")
        finally:
            # Restore original mtime
            try:
                os.utime(DATA_FILE, (original_mtime, original_mtime))
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
