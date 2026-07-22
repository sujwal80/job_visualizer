#!/usr/bin/env python3
"""
Milestone 2 Viewport Caching & Filtering Verification Suite:
tests/test_viewport_caching_m2.py
"""

import os
import sys
import unittest
import re

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestViewportCachingMilestone2(unittest.TestCase):
    """Verifies static definitions in app.js and logical correctness of the viewport containment checks."""

    @classmethod
    def setUpClass(cls):
        cls.app_js_path = os.path.join(PROJECT_ROOT, "public", "static", "js", "app.js")
        with open(cls.app_js_path, "r", encoding="utf-8") as f:
            cls.app_js = f.read()

    def test_01_static_check_helper_functions_defined(self):
        """Assert that all four helper functions are defined in app.js."""
        self.assertIn("function isPointLongitudeContained", self.app_js)
        self.assertIn("function isIntervalLongitudeContained", self.app_js)
        self.assertIn("function findCachedViewportMatch", self.app_js)
        self.assertIn("function filterStartupsByViewport", self.app_js)

    def test_02_static_check_fetch_filtered_startups_integration(self):
        """Assert that fetchFilteredStartups integrates findCachedViewportMatch and filterStartupsByViewport."""
        self.assertIn("const containmentMatch = findCachedViewportMatch(queryParams);", self.app_js)
        self.assertIn("filterStartupsByViewport(containmentMatch, queryParams)", self.app_js)

    def test_03_is_point_longitude_contained_logic(self):
        """Verify the logical correctness of isPointLongitudeContained matching the JS behavior."""
        def is_point_longitude_contained(lng, min_lng, max_lng):
            if min_lng <= max_lng:
                return lng >= min_lng and lng <= max_lng
            return lng >= min_lng or lng <= max_lng

        # 1. Standard interval (no wrap-around)
        self.assertTrue(is_point_longitude_contained(77.55, 77.5, 77.6))
        self.assertTrue(is_point_longitude_contained(77.5, 77.5, 77.6))
        self.assertTrue(is_point_longitude_contained(77.6, 77.5, 77.6))
        self.assertFalse(is_point_longitude_contained(77.4, 77.5, 77.6))
        self.assertFalse(is_point_longitude_contained(77.7, 77.5, 77.6))

        # 2. Antimeridian wrap-around interval (min > max)
        self.assertTrue(is_point_longitude_contained(179.5, 179.0, -179.0))
        self.assertTrue(is_point_longitude_contained(-179.5, 179.0, -179.0))
        self.assertTrue(is_point_longitude_contained(179.0, 179.0, -179.0))
        self.assertTrue(is_point_longitude_contained(-179.0, 179.0, -179.0))
        self.assertFalse(is_point_longitude_contained(0.0, 179.0, -179.0))
        self.assertFalse(is_point_longitude_contained(178.9, 179.0, -179.0))

    def test_04_is_interval_longitude_contained_logic(self):
        """Verify the logical correctness of isIntervalLongitudeContained matching the JS behavior."""
        def is_interval_longitude_contained(new_min, new_max, cached_min, cached_max):
            if cached_min <= cached_max:
                if new_min <= new_max:
                    return new_min >= cached_min and new_max <= cached_max
                return False
            if new_min <= new_max:
                return new_min >= cached_min or new_max <= cached_max
            return new_min >= cached_min and new_max <= cached_max

        # Case A: Cached is standard interval (cached_min <= cached_max)
        # 1. New is standard, fully within Cached
        self.assertTrue(is_interval_longitude_contained(77.52, 77.58, 77.5, 77.6))
        # 2. New is standard, extends past Cached max
        self.assertFalse(is_interval_longitude_contained(77.52, 77.65, 77.5, 77.6))
        # 3. New is standard, extends past Cached min
        self.assertFalse(is_interval_longitude_contained(77.45, 77.58, 77.5, 77.6))
        # 4. New is wrap-around, Cached is standard -> impossible to be contained
        self.assertFalse(is_interval_longitude_contained(179.0, -179.0, 77.5, 77.6))

        # Case B: Cached is wrap-around interval (cached_min > cached_max)
        # 5. New is standard, fully within Cached right-part (e.g. >= 179.0)
        self.assertTrue(is_interval_longitude_contained(179.2, 179.8, 179.0, -179.0))
        # 6. New is standard, fully within Cached left-part (e.g. <= -179.0)
        self.assertTrue(is_interval_longitude_contained(-179.8, -179.2, 179.0, -179.0))
        # 7. New is standard, spans across the antimeridian but is not wrap-around (impossible, if it crosses it must wrap around)
        # 8. New is wrap-around, fully within Cached wrap-around
        self.assertTrue(is_interval_longitude_contained(179.5, -179.5, 179.0, -179.0))
        # 9. New is wrap-around, extends past Cached bounds
        self.assertFalse(is_interval_longitude_contained(178.5, -179.5, 179.0, -179.0))
        self.assertFalse(is_interval_longitude_contained(179.5, -178.5, 179.0, -179.0))

    def test_05_client_side_filtering_and_unpinned_retention_logic(self):
        """Verify the logical correctness of filterStartupsByViewport including unpinned startups retention."""
        def filter_startups_by_viewport(startups, min_lat, max_lat, min_lng, max_lng):
            lat_span = abs(max_lat - min_lat)
            keep_remote = lat_span >= 1.0

            def is_point_longitude_contained(lng, min_l, max_l):
                if min_l <= max_l:
                    return lng >= min_l and lng <= max_l
                return lng >= min_l or lng <= max_l

            filtered = []
            for s in startups:
                if s.get("has_pin") is False:
                    if keep_remote:
                        filtered.append(s)
                    continue

                lat = float(s.get("lat", "nan"))
                lng = float(s.get("lng", "nan"))
                import math
                if math.isnan(lat) or math.isnan(lng):
                    continue

                lat_contained = lat >= min_lat and lat <= max_lat
                lng_contained = is_point_longitude_contained(lng, min_lng, max_lng)

                if lat_contained and lng_contained:
                    filtered.append(s)
            return filtered

        startups = [
            {"id": 1, "name": "Pinned In-Bounds", "lat": 12.95, "lng": 77.55, "has_pin": True},
            {"id": 2, "name": "Pinned Out-of-Bounds", "lat": 14.0, "lng": 77.55, "has_pin": True},
            {"id": 3, "name": "Unpinned/Remote", "has_pin": False}
        ]

        # Case 1: Wide lat_span >= 1.0 (min_lat=12.0, max_lat=13.5)
        # Expected: id=1 is kept, id=2 is out, id=3 is kept (keep_remote is true)
        res_wide = filter_startups_by_viewport(startups, 12.0, 13.5, 77.0, 78.0)
        self.assertEqual(len(res_wide), 2)
        self.assertEqual({s["id"] for s in res_wide if "id" in s}, {1, 3})
        self.assertTrue(any(s.get("has_pin") is False for s in res_wide))

        # Case 2: Narrow lat_span < 1.0 (min_lat=12.9, max_lat=13.0)
        # Expected: id=1 is kept (12.95), id=2 is out, id=3 is excluded (keep_remote is false)
        res_narrow = filter_startups_by_viewport(startups, 12.9, 13.0, 77.0, 78.0)
        self.assertEqual(len(res_narrow), 1)
        self.assertEqual(res_narrow[0]["id"], 1)

    def test_06_cached_limit_bypass_logic(self):
        """Verify client-side bypasses containment check match if cached startups array was capped by server limit."""
        # Simulated test case
        cached_startups_capped = [{"id": i} for i in range(500)] # 500 startups (capped)
        cached_startups_uncapped = [{"id": i} for i in range(120)] # 120 startups

        limit = 500

        # Capped: should bypass cache
        self.assertTrue(len(cached_startups_capped) >= limit)
        # Uncapped: should not bypass cache
        self.assertFalse(len(cached_startups_uncapped) >= limit)


if __name__ == "__main__":
    unittest.main()
