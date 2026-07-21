#!/usr/bin/env python3
"""
Verification Suite for Milestone 3: Frontend Multi-Layer Caching, Request Coalescing,
X-Data-Version Auto-Invalidation, Zero-API Filtering, and Clean Empty States.
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestMilestone3FrontendCachingAndCoalescing(unittest.TestCase):
    """Verifies complete JS implementation of Milestone 3 requirements."""

    @classmethod
    def setUpClass(cls):
        cls.state_js_path = os.path.join(PROJECT_ROOT, "public", "static", "js", "modules", "state.js")
        cls.api_js_path = os.path.join(PROJECT_ROOT, "public", "static", "js", "modules", "api.js")
        cls.ui_manager_js_path = os.path.join(PROJECT_ROOT, "public", "static", "js", "modules", "ui_manager.js")
        cls.router_js_path = os.path.join(PROJECT_ROOT, "public", "static", "js", "modules", "router.js")
        cls.app_js_path = os.path.join(PROJECT_ROOT, "public", "static", "js", "app.js")

        with open(cls.state_js_path, "r", encoding="utf-8") as f:
            cls.state_js = f.read()
        with open(cls.api_js_path, "r", encoding="utf-8") as f:
            cls.api_js = f.read()
        with open(cls.ui_manager_js_path, "r", encoding="utf-8") as f:
            cls.ui_manager_js = f.read()
        with open(cls.router_js_path, "r", encoding="utf-8") as f:
            cls.router_js = f.read()
        with open(cls.app_js_path, "r", encoding="utf-8") as f:
            cls.app_js = f.read()

    def test_01_lru_cache_with_ttl_class_implementation(self):
        """Verify LRUCacheWithTTL class is properly structured with TTL and web storage support."""
        self.assertIn("export class LRUCacheWithTTL", self.state_js, "state.js must export LRUCacheWithTTL class.")
        self.assertIn("set(key, value, ttl = this.defaultTTL)", self.state_js, "LRUCacheWithTTL must support set with optional custom TTL.")
        self.assertIn("get(key)", self.state_js, "LRUCacheWithTTL must implement get(key).")
        self.assertIn("has(key)", self.state_js, "LRUCacheWithTTL must implement has(key).")
        self.assertIn("clear()", self.state_js, "LRUCacheWithTTL must implement clear().")
        self.assertIn("now >= item.expiry", self.state_js, "get(key) must verify expiration against Date.now().")
        self.assertIn("sessionStorage", self.state_js, "LRUCacheWithTTL must support sessionStorage backend.")
        self.assertIn("localStorage", self.state_js, "LRUCacheWithTTL must support localStorage backend.")

    def test_02_cache_tiers_instantiation(self):
        """Verify QueryCache, ProfileCache, and GeocodeCache instantiation in state object."""
        self.assertIn("queryCache: new LRUCacheWithTTL({ capacity: 50, defaultTTL: 120000, storage: null })", self.state_js,
                      "QueryCache must be instantiated with 120,000ms (2-minute) SWR TTL.")
        self.assertIn("profileCache: new LRUCacheWithTTL({ capacity: 50, defaultTTL: 300000, storage: 'sessionStorage', prefix: 'wtm_profile_' })", self.state_js,
                      "ProfileCache must be instantiated with 300,000ms (5-minute) TTL backed by sessionStorage.")
        self.assertIn("geocodeCache: new LRUCacheWithTTL({ capacity: 50, defaultTTL: 86400000, storage: 'localStorage', prefix: 'wtm_geocode_' })", self.state_js,
                      "GeocodeCache must be instantiated with 86,400,000ms (24-hour) TTL backed by localStorage.")
        self.assertIn("inFlightPromises: new Map()", self.state_js,
                      "inFlightPromises Map must be maintained in state.")
        self.assertIn("currentDataVersion: null", self.state_js,
                      "currentDataVersion must be tracked in state.")

    def test_03_request_coalescing_implementation(self):
        """Verify fetchFilteredStartups and selectAndOpenStartup coalesce concurrent calls via inFlightPromises."""
        # Check selectAndOpenStartup in ui_manager.js
        self.assertIn("state.profileCache.has(", self.ui_manager_js, "selectAndOpenStartup must check ProfileCache first.")
        self.assertIn("state.inFlightPromises.has(", self.ui_manager_js, "selectAndOpenStartup must check inFlightPromises.")
        self.assertIn("state.inFlightPromises.set(", self.ui_manager_js, "selectAndOpenStartup must store fetch promise in inFlightPromises.")
        self.assertIn("state.inFlightPromises.delete(", self.ui_manager_js, "selectAndOpenStartup must clean up inFlightPromises in .finally().")

        # Check fetchFilteredStartups in app.js
        self.assertIn("state.queryCache.has(url)", self.app_js, "fetchFilteredStartups must check QueryCache first.")
        self.assertIn("state.inFlightPromises.has(url)", self.app_js, "fetchFilteredStartups must check inFlightPromises for request coalescing.")
        self.assertIn("state.inFlightPromises.set(url, promise)", self.app_js, "fetchFilteredStartups must store fetch promise in inFlightPromises.")
        self.assertIn("state.inFlightPromises.delete(url)", self.app_js, "fetchFilteredStartups must clean up inFlightPromises in .finally().")

    def test_04_x_data_version_auto_invalidation(self):
        """Verify X-Data-Version response header check and automatic cache invalidation in safeFetch."""
        self.assertIn("X-Data-Version", self.api_js, "safeFetch must inspect X-Data-Version response header.")
        self.assertIn("state.queryCache.clear()", self.api_js, "safeFetch must automatically clear queryCache on data version change.")
        self.assertIn("state.profileCache.clear()", self.api_js, "safeFetch must automatically clear profileCache on data version change.")
        self.assertIn("state.currentDataVersion = dataVersion", self.api_js, "safeFetch must record currentDataVersion.")

    def test_05_zero_api_local_filtering(self):
        """Verify local filtering and search input execute purely in-memory on state.startupsData."""
        self.assertIn("state.startupsData.filter(startup => checkStartupMatch(startup, searchText))", self.app_js,
                      "applyFiltering() must run purely in-memory on state.startupsData.")
        self.assertIn("renderDirectory(filtered", self.app_js,
                      "applyFiltering() must directly render local filtered results without API calls.")

    def test_06_clean_empty_state_and_short_ttl(self):
        """Verify clean empty state display ('No companies actively hiring in this location.') and 60-second TTL for empty arrays."""
        self.assertIn("No companies actively hiring in this location.", self.ui_manager_js,
                      "renderDirectory must cleanly render 'No companies actively hiring in this location.' for empty states.")
        self.assertIn("startups.length === 0 ? 60000 : 120000", self.app_js,
                      "fetchFilteredStartups must cache empty results [] with a 60,000ms (60s) TTL instead of standard 120s TTL.")

    def test_07_geocode_cache_integration(self):
        """Verify geocoding lookup checks GeocodeCache in router.js."""
        self.assertIn("state.geocodeCache.get(lowerCity)", self.router_js,
                      "Geocoder lookup must check state.geocodeCache first.")
        self.assertTrue(
            "state.geocodeCache.set(lowerCity, [lon, lat])" in self.router_js or
            "state.geocodeCache.set(lowerCity, cachedVal)" in self.router_js,
            "Successful geocoder lookups must be stored in state.geocodeCache."
        )


if __name__ == "__main__":
    unittest.main()
