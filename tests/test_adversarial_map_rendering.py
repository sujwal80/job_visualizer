#!/usr/bin/env python3
"""
Adversarial test suite for Map Marker Rendering, Caching, and Coordinate Registry Drift:
tests/test_adversarial_map_rendering.py
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


class TestAdversarialMapRendering(unittest.TestCase):
    """Adversarial/Stress test suite for Map Rendering, DOM element persistence, and coordinate drift."""

    BASE_URL = "http://127.0.0.1:5019"

    @classmethod
    def setUpClass(cls):
        """Manage backend server lifecycle and start Playwright headless Chromium for tests."""
        cls.server_thread = None
        cls.server = None
        cls.server_ready = False

        if PLAYWRIGHT_AVAILABLE:
            # Check if a backend server is already running on 5019
            try:
                with urllib.request.urlopen(f"{cls.BASE_URL}/api/companies?limit=1", timeout=1) as response:
                    if response.status == 200:
                        cls.server_ready = True
            except Exception:
                cls.server_ready = False

            if not cls.server_ready:
                from werkzeug.serving import make_server
                app.testing = True
                cls.server = make_server("127.0.0.1", 5019, app, threaded=True)
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
        `;
        document.head.appendChild(style);
        """
        self.page.route(re.compile(r"https://cdn\.tailwindcss\.com.*"), lambda route: route.fulfill(
            status=200,
            content_type="text/javascript",
            body=tailwind_mock_js
        ))
        
        # We mock maplibregl precisely to control map bounds and trigger custom moveend events
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
                Marker: function(opts) {
                    const el = (opts && opts.element) || document.createElement('div');
                    el.className = (el.className || '') + ' logo-marker-container';
                    this.setLngLat = function(coords) {
                        this.lngLat = coords;
                        return this;
                    };
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

    def tearDown(self):
        """Close browser page and context and assert zero JS errors."""
        if hasattr(self, 'page') and self.page:
            self.page.close()
        if hasattr(self, 'context') and self.context:
            self.context.close()
        if hasattr(self, 'js_errors'):
            self.assertEqual(self.js_errors, [], f"JS runtime errors captured: {self.js_errors}")

    def test_coordinate_rounding_and_drift_adversarial(self):
        """Verify precision jittering of overlapping coordinates, original coordinates preservation, and zero drift over multiple updates."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        # Mock /api/companies to return startups with identical coordinates
        mock_startups = [
            {
                "id": 101,
                "name": "Overlapper A",
                "lat": 12.97160001,
                "lng": 77.59460001,
                "has_pin": True,
                "city": "Bengaluru",
                "job_count": 2,
                "jobs": [{"title": "Eng 1", "source": "LinkedIn"}]
            },
            {
                "id": 102,
                "name": "Overlapper B",
                "lat": 12.97160002,
                "lng": 77.59460002,
                "has_pin": True,
                "city": "Bengaluru",
                "job_count": 1,
                "jobs": [{"title": "Eng 2", "source": "LinkedIn"}]
            },
            {
                "id": 103,
                "name": "Overlapper C",
                "lat": 12.97160003,
                "lng": 77.59460003,
                "has_pin": True,
                "city": "Bengaluru",
                "job_count": 1,
                "jobs": [{"title": "Eng 3", "source": "LinkedIn"}]
            }
        ]

        # Intercept api/companies requests
        self.page.route(re.compile(r".*/api/companies.*"), lambda route: route.fulfill(
            status=200,
            headers={"X-Data-Version": "1.0"},
            content_type="application/json",
            body=json.dumps(mock_startups)
        ))

        # 1. Load the page with city=Bengaluru
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru")
        self.page.wait_for_load_state("domcontentloaded")

        # Wait for data to load
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && "
            "window.WorldTechApp.state && "
            "window.WorldTechApp.state.startupsData && "
            "window.WorldTechApp.state.startupsData.length === 3"
        )

        # 2. Verify jittering occurred and original coordinates are preserved
        startup_a, startup_b, startup_c = self.page.evaluate("""() => {
            const data = window.WorldTechApp.state.startupsData;
            return [
                data.find(s => s.id === 101),
                data.find(s => s.id === 102),
                data.find(s => s.id === 103)
            ];
        }""")

        # Verify orig_lat and orig_lng are preserved exactly as original coordinates
        self.assertEqual(startup_a["orig_lat"], 12.97160001)
        self.assertEqual(startup_a["orig_lng"], 77.59460001)
        self.assertEqual(startup_b["orig_lat"], 12.97160002)
        self.assertEqual(startup_b["orig_lng"], 77.59460002)
        self.assertEqual(startup_c["orig_lat"], 12.97160003)
        self.assertEqual(startup_c["orig_lng"], 77.59460003)

        # Startup A should be processed first, no jitter
        self.assertAlmostEqual(startup_a["lat"], 12.97160001, places=8)
        self.assertAlmostEqual(startup_a["lng"], 77.59460001, places=8)

        # Startup B should be offsetted
        self.assertNotEqual(startup_b["lat"], startup_b["orig_lat"])
        self.assertNotEqual(startup_b["lng"], startup_b["orig_lng"])

        # Startup C should be offsetted further
        self.assertTrue(startup_c["lat"] != startup_c["orig_lat"] or startup_c["lng"] != startup_c["orig_lng"])
        self.assertTrue(startup_c["lat"] != startup_b["lat"] or startup_c["lng"] != startup_b["lng"])

        # Save coordinates after initial render
        first_a_lat, first_a_lng = startup_a["lat"], startup_a["lng"]
        first_b_lat, first_b_lng = startup_b["lat"], startup_b["lng"]
        first_c_lat, first_c_lng = startup_c["lat"], startup_c["lng"]

        # 3. Adversarial Check: trigger multiple updates using the SAME dataset (e.g. simulating multiple pans)
        # We call updateMarkersDiff programmatically in the browser multiple times
        for update_idx in range(5):
            self.page.evaluate("""() => {
                const data = window.WorldTechApp.state.startupsData;
                // Re-run marker update
                window.WorldTechApp.updateMarkersDiff(data);
            }""")
            
            # Fetch coordinates again
            curr_a, curr_b, curr_c = self.page.evaluate("""() => {
                const data = window.WorldTechApp.state.startupsData;
                return [
                    data.find(s => s.id === 101),
                    data.find(s => s.id === 102),
                    data.find(s => s.id === 103)
                ];
            }""")

            # Coordinates MUST NOT drift! They should remain exactly equal to the first jittered values.
            self.assertEqual(curr_a["lat"], first_a_lat, f"Startup A lat drifted on update {update_idx}")
            self.assertEqual(curr_a["lng"], first_a_lng, f"Startup A lng drifted on update {update_idx}")
            self.assertEqual(curr_b["lat"], first_b_lat, f"Startup B lat drifted on update {update_idx}")
            self.assertEqual(curr_b["lng"], first_b_lng, f"Startup B lng drifted on update {update_idx}")
            self.assertEqual(curr_c["lat"], first_c_lat, f"Startup C lat drifted on update {update_idx}")
            self.assertEqual(curr_c["lng"], first_c_lng, f"Startup C lng drifted on update {update_idx}")

    def test_marker_element_identity_preservation(self):
        """Verify that existing marker DOM elements are preserved and updated, not recreated, to maintain element identity."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        # Intercept api/companies requests
        mock_startups = [
            {
                "id": 201,
                "name": "Persistent Marker Co",
                "lat": 12.95,
                "lng": 77.55,
                "has_pin": True,
                "city": "Bengaluru",
                "job_count": 1,
                "jobs": [{"title": "Developer", "source": "LinkedIn"}]
             }
        ]
        self.page.route(re.compile(r".*/api/companies.*"), lambda route: route.fulfill(
            status=200,
            headers={"X-Data-Version": "1.0"},
            content_type="application/json",
            body=json.dumps(mock_startups)
        ))

        # Load page
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && "
            "window.WorldTechApp.state.startupsData.length === 1"
        )

        # Tag the DOM element of the marker with a custom attribute
        self.page.evaluate("""() => {
            const marker = window.WorldTechApp.state.markersMap.get(201);
            if (marker && typeof marker.getElement === 'function') {
                const el = marker.getElement();
                el.setAttribute('data-test-identity', 'preserved-element-12345');
                el.__custom_identity_flag = 'preserved-flag-9999';
            }
        }""")

        # Call updateMarkersDiff again with the same startup list to simulate a refilter or map panning return
        self.page.evaluate("""() => {
            const data = window.WorldTechApp.state.startupsData;
            window.WorldTechApp.updateMarkersDiff(data);
        }""")

        # Verify the custom attribute and property still exist on the DOM element
        has_identity_attr, has_identity_prop = self.page.evaluate("""() => {
            const marker = window.WorldTechApp.state.markersMap.get(201);
            if (!marker || typeof marker.getElement !== 'function') return [false, false];
            const el = marker.getElement();
            return [
                el.getAttribute('data-test-identity') === 'preserved-element-12345',
                el.__custom_identity_flag === 'preserved-flag-9999'
            ];
        }""")

        self.assertTrue(has_identity_attr, "Marker DOM element attribute was lost - element was likely recreated")
        self.assertTrue(has_identity_prop, "Marker DOM element custom JS property was lost - element was likely recreated")

    def test_cache_hit_rate_panning_zooming(self):
        """Verify client-side cache containment hit/miss behavior during panning/zooming."""
        if not PLAYWRIGHT_AVAILABLE or not self.server_ready:
            self.skipTest("Playwright or local Flask test server is not available.")

        request_urls = []
        def handle_request(request):
            if "/api/companies" in request.url:
                request_urls.append(request.url)

        self.page.on("request", handle_request)

        # 1. Load initial location (Bengaluru)
        self.page.goto(f"{self.BASE_URL}/jobs?city=Bengaluru")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_function(
            "() => typeof window.WorldTechApp !== 'undefined' && "
            "window.WorldTechApp.state.startupsData.length > 0"
        )

        self.assertEqual(len(request_urls), 1, f"Expected 1 request on load. URLs: {request_urls}")

        # Let's save the current bounding box
        initial_bounds = self.page.evaluate("window.WorldTechApp.map.getBounds()")
        
        # 2. Pan map slightly (which misses cache because bounds changed)
        self.page.evaluate("""() => {
            const center = window.WorldTechApp.map.getCenter();
            window.WorldTechApp.map.center = { lng: center.lng + 0.05, lat: center.lat + 0.05 };
            window.WorldTechApp.map.fire('moveend', { originalEvent: {} });
        }""")
        self.page.wait_for_timeout(1000)

        # The pan should trigger a new api request because bounds shifted outside cached area
        self.assertEqual(len(request_urls), 2, f"Expected 2 requests after pan. URLs: {request_urls}")

        # Record bounds of the second request (which is now the "cached outer bounds")
        outer_bounds = self.page.evaluate("window.WorldTechApp.map.getBounds()")

        # 3. Zoom in (which decreases viewport size, placing it entirely inside the cached outer bounds)
        self.page.evaluate("""() => {
            const z = window.WorldTechApp.map.getZoom();
            window.WorldTechApp.map.setZoom(z + 1.5);
            window.WorldTechApp.map.fire('moveend', { originalEvent: {} });
        }""")
        self.page.wait_for_timeout(1000)

        # Zooming in should hit the containment cache, so NO new request should be dispatched!
        self.assertEqual(len(request_urls), 2, f"Zooming in should HIT cache. Requests dispatched: {request_urls}")

        # 4. Zoom out back to a larger area (which exceeds the cached outer bounds)
        self.page.evaluate("""() => {
            const z = window.WorldTechApp.map.getZoom();
            window.WorldTechApp.map.setZoom(z - 2.5); // zoom out past original panned zoom
            window.WorldTechApp.map.fire('moveend', { originalEvent: {} });
        }""")
        self.page.wait_for_timeout(1000)

        # Zooming out should exceed the cached bounds, triggering a cache miss and a new API request
        self.assertEqual(len(request_urls), 3, f"Zooming out should MISS cache. Requests dispatched: {request_urls}")


if __name__ == "__main__":
    unittest.main()
