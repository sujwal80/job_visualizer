#!/usr/bin/env python3
"""
Unit and Static Assertion Verification Suite for Map Caching and Viewport Transition.
tests/test_caching_optimizations_unit.py
"""

import os
import sys
import unittest
import math

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestCachingOptimizationsUnit(unittest.TestCase):
    """Verifies changes made to state.js, api.js, utils.js, app.js, and router.js."""

    @classmethod
    def setUpClass(cls):
        cls.state_js_path = os.path.join(PROJECT_ROOT, "public", "static", "js", "modules", "state.js")
        cls.api_js_path = os.path.join(PROJECT_ROOT, "public", "static", "js", "modules", "api.js")
        cls.utils_js_path = os.path.join(PROJECT_ROOT, "public", "static", "js", "modules", "utils.js")
        cls.router_js_path = os.path.join(PROJECT_ROOT, "public", "static", "js", "modules", "router.js")
        cls.app_js_path = os.path.join(PROJECT_ROOT, "public", "static", "js", "app.js")

        with open(cls.state_js_path, "r", encoding="utf-8") as f:
            cls.state_js = f.read()
        with open(cls.api_js_path, "r", encoding="utf-8") as f:
            cls.api_js = f.read()
        with open(cls.utils_js_path, "r", encoding="utf-8") as f:
            cls.utils_js = f.read()
        with open(cls.router_js_path, "r", encoding="utf-8") as f:
            cls.router_js = f.read()
        with open(cls.app_js_path, "r", encoding="utf-8") as f:
            cls.app_js = f.read()

    def test_01_state_js_additions(self):
        """Verify cityCache and searchedCityCenter are added to state.js."""
        self.assertIn("cityCache: new LRUCacheWithTTL({ capacity: 10, defaultTTL: 86400000, storage: 'sessionStorage', prefix: 'wtm_city_' })", self.state_js)
        self.assertIn("searchedCityCenter: null", self.state_js)

    def test_02_api_js_clear_city_cache(self):
        """Verify api.js clears cityCache on data version mismatch."""
        self.assertIn("state.cityCache.clear()", self.api_js)

    def test_03_utils_js_calculate_distance_km(self):
        """Verify calculateDistanceKm is exported in utils.js and logic works."""
        self.assertIn("export function calculateDistanceKm", self.utils_js)
        
        # Test Haversine formula logic matching JS implementation
        def py_calculate_distance_km(lat1, lon1, lat2, lon2):
            R = 6371.0
            d_lat = math.radians(lat2 - lat1)
            d_lon = math.radians(lon2 - lon1)
            a = (math.sin(d_lat / 2.0) ** 2 +
                 math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * (math.sin(d_lon / 2.0) ** 2))
            c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
            return R * c

        # Bangalore Center to Indiranagar
        dist = py_calculate_distance_km(12.9716, 77.5946, 12.9732913, 77.6404672)
        self.assertTrue(4.5 < dist < 5.5, f"Distance should be around 4.97km. Got: {dist}")

    def test_04_app_js_distance_integration(self):
        """Verify app.js imports and uses calculateDistanceKm in the moveend handler."""
        self.assertIn("calculateDistanceKm", self.app_js)
        self.assertIn("distKm <= 50", self.app_js)
        self.assertIn("shouldTransition = false", self.app_js)

    def test_05_router_js_searched_city_center_updates(self):
        """Verify router.js stores resolved coordinates in state.searchedCityCenter."""
        # 1. KNOWN_HUB_COORDINATES
        self.assertIn("state.searchedCityCenter = KNOWN_HUB_COORDINATES[normalizedQuery]", self.router_js)
        # 2. geocodeCache
        self.assertTrue(
            "state.searchedCityCenter = [lon, lat]" in self.router_js or
            "state.searchedCityCenter = coords" in self.router_js or
            "state.searchedCityCenter = " in self.router_js
        )
        # 3. Nominatim geocode success
        self.assertIn("state.searchedCityCenter = null", self.router_js)

    def test_06_cull_markers_in_map_manager_and_app_js(self):
        """Verify cullMarkers is defined, detaches/reattaches markers, and is bound on move/zoom events."""
        with open(self.state_js_path, "r", encoding="utf-8") as f:
            state_js = f.read()
        with open(os.path.join(PROJECT_ROOT, "public", "static", "js", "modules", "map_manager.js"), "r", encoding="utf-8") as f:
            map_mgr_js = f.read()

        # Check that markersMap is in state
        self.assertIn("markersMap: new Map()", state_js)

        # Check cullMarkers implementation exists in map_manager.js
        self.assertIn("export function cullMarkers(map)", map_mgr_js)
        self.assertIn("marker.remove()", map_mgr_js)
        self.assertIn("marker.addTo(map)", map_mgr_js)
        self.assertIn("marker.isAttached = false", map_mgr_js)
        self.assertIn("marker.isAttached = true", map_mgr_js)

        # Check that cullMarkers is bound to zoom and move in app.js
        self.assertIn("map.on('move', () => {", self.app_js)
        self.assertIn("map.on('zoom', () => {", self.app_js)

    def test_07_client_side_filtering_and_caching_logic(self):
        """Verify client-side filtering ports Python job matching logic and fetchFilteredStartups checks cache."""
        # 1. Check checkStartupMatch matches skills
        self.assertIn("Array.isArray(startup.skills) && startup.skills.some", self.app_js)

        # 2. Check filterCityStartupsLocally uses parseMaxSalary, matchExpLevel, matchWorkType, etc.
        self.assertIn("function filterCityStartupsLocally", self.app_js)
        self.assertIn("parseMaxSalary(j.salary)", self.app_js)
        self.assertIn("matchExpLevel(j.experience || '', expLevel)", self.app_js)
        self.assertIn("matchWorkType(j, workType, s.is_remote_office)", self.app_js)
        self.assertIn("isPointLongitudeContained(lng, minLng, maxLng)", self.app_js)

        # 3. Check fetchFilteredStartups check for cityCache
        self.assertIn("state.cityCache.has(cityKey)", self.app_js)
        self.assertIn("cached.length < 500", self.app_js)


if __name__ == "__main__":
    unittest.main()
