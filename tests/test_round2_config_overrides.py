#!/usr/bin/env python3
"""
Test Suite: tests/test_round2_config_overrides.py
Automated unit and verification tests asserting externalized configurations
(backend.config and data_acquisition.geo_config), fallback coordinate matching,
synonym matching, and environment variable override behavior.
"""

import unittest
import unittest.mock as mock
import os
import sys
import importlib

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import backend.config
import data_acquisition.geo_config
import backend.utils.validators
from data_acquisition.geo_config import is_fallback_coordinate, match_target_city


class TestDefaultConfigurationLoading(unittest.TestCase):
    """Verifies default values loaded from backend.config and data_acquisition.geo_config."""

    def test_backend_config_defaults(self):
        self.assertEqual(backend.config.DEFAULT_TARGET_CITY, "Bengaluru")
        self.assertAlmostEqual(backend.config.DEFAULT_MAP_CENTER_LAT, 12.9716)
        self.assertAlmostEqual(backend.config.DEFAULT_MAP_CENTER_LNG, 77.5946)
        self.assertIn((12.9716, 77.5946), backend.config.FALLBACK_COORDINATES)
        self.assertAlmostEqual(backend.config.PIN_DELTA_THRESHOLD, 0.008)
        self.assertIn("bengaluru", backend.config.GENERIC_HUB_LABELS)
        self.assertIn("bangalore", backend.config.GENERIC_HUB_LABELS)

    def test_geo_config_defaults(self):
        self.assertEqual(data_acquisition.geo_config.DEFAULT_TARGET_CITY, "Bengaluru")
        self.assertIn((12.9716, 77.5946), data_acquisition.geo_config.FALLBACK_COORDINATES)
        self.assertIn("https://www.google.com", data_acquisition.geo_config.TEST_FIXTURE_WHITELIST_URLS)
        self.assertAlmostEqual(data_acquisition.geo_config.PIN_DELTA_THRESHOLD, 0.008)
        self.assertIn("koramangala", data_acquisition.geo_config.DEFAULT_GEO_LOCALITIES)


class TestGeoConfigHelperFunctions(unittest.TestCase):
    """Verifies behavior of helper functions in data_acquisition.geo_config under default config."""

    def test_is_fallback_coordinate_default(self):
        # Known default fallback coordinates should return True
        self.assertTrue(is_fallback_coordinate(12.9716, 77.5946))
        self.assertTrue(is_fallback_coordinate(12.9767936, 77.590082))
        # Specific coordinates away from fallback centers return False
        self.assertFalse(is_fallback_coordinate(12.9352, 77.6245))
        # Invalid / None inputs return False gracefully
        self.assertFalse(is_fallback_coordinate(None, 77.5946))
        self.assertFalse(is_fallback_coordinate("invalid_lat", "invalid_lng"))

    def test_match_target_city_synonyms(self):
        # Target city matching with regional synonyms
        self.assertTrue(match_target_city("Bangalore, India", "Bengaluru"))
        self.assertTrue(match_target_city("Bengaluru", "Bangalore"))
        self.assertTrue(match_target_city("Hyderabad, Telangana", "Hyderabad"))
        self.assertTrue(match_target_city("Bombay, Maharashtra", "Mumbai"))
        # Non-matching target cities
        self.assertFalse(match_target_city("Delhi", "Bengaluru"))
        self.assertFalse(match_target_city(None, "Bengaluru"))
        self.assertFalse(match_target_city("Bengaluru", None))


class TestBackendValidatorsCheckHasPin(unittest.TestCase):
    """Verifies backend.utils.validators._check_has_pin behavior under default configuration."""

    def test_check_has_pin_default_behavior(self):
        # Startup with generic fallback coordinate returns False
        self.assertFalse(backend.utils.validators._check_has_pin({
            "lat": 12.9716,
            "lng": 77.5946,
            "city": "Bengaluru"
        }))
        # Startup with generic hub city name and missing coordinates returns False
        self.assertFalse(backend.utils.validators._check_has_pin({
            "lat": None,
            "lng": None,
            "city": "Bengaluru"
        }))
        # Startup with specific street address and distinct coordinates returns True
        self.assertTrue(backend.utils.validators._check_has_pin({
            "lat": 12.9352,
            "lng": 77.6245,
            "address": "Koramangala 4th Block, Bengaluru"
        }))
        # Startup close to fallback coordinate within PIN_DELTA_THRESHOLD returns False
        self.assertFalse(backend.utils.validators._check_has_pin({
            "lat": 12.97165,
            "lng": 77.59462,
            "address": "Bengaluru"
        }))


class TestConfigurationEnvironmentOverrides(unittest.TestCase):
    """Verifies that overriding environment variables dynamically updates module configurations and behavior."""

    def setUp(self):
        self._reload_all_configs()

    def tearDown(self):
        self._reload_all_configs()

    def _reload_all_configs(self):
        importlib.reload(backend.config)
        importlib.reload(data_acquisition.geo_config)
        importlib.reload(backend.utils.validators)

    def test_override_backend_config_env_vars(self):
        env_patch = {
            "DEFAULT_TARGET_CITY": "Hyderabad",
            "DEFAULT_MAP_CENTER_LAT": "17.3850",
            "DEFAULT_MAP_CENTER_LNG": "78.4867",
            "PIN_DELTA_THRESHOLD": "0.015"
        }
        with mock.patch.dict(os.environ, env_patch):
            importlib.reload(backend.config)
            self.assertEqual(backend.config.DEFAULT_TARGET_CITY, "Hyderabad")
            self.assertAlmostEqual(backend.config.DEFAULT_MAP_CENTER_LAT, 17.3850)
            self.assertAlmostEqual(backend.config.DEFAULT_MAP_CENTER_LNG, 78.4867)
            self.assertAlmostEqual(backend.config.PIN_DELTA_THRESHOLD, 0.015)

    def test_override_geo_config_env_vars(self):
        env_patch = {
            "DEFAULT_TARGET_CITY": "Mumbai",
            "TEST_FIXTURE_WHITELIST_URLS": "https://example.org,http://test.io",
            "GEO_LOCALITIES": "bandra,andheri,powai"
        }
        with mock.patch.dict(os.environ, env_patch):
            importlib.reload(data_acquisition.geo_config)
            self.assertEqual(data_acquisition.geo_config.DEFAULT_TARGET_CITY, "Mumbai")
            self.assertEqual(
                data_acquisition.geo_config.TEST_FIXTURE_WHITELIST_URLS,
                ["https://example.org", "http://test.io"]
            )
            self.assertEqual(
                data_acquisition.geo_config.DEFAULT_GEO_LOCALITIES,
                ["bandra", "andheri", "powai"]
            )

    def test_override_fallback_coordinates_behavior(self):
        env_patch = {
            "FALLBACK_COORDINATES": "10.0,20.0;30.0,40.0"
        }
        with mock.patch.dict(os.environ, env_patch):
            self._reload_all_configs()
            # Assert overridden fallback coordinates are loaded
            self.assertEqual(
                data_acquisition.geo_config.FALLBACK_COORDINATES,
                [(10.0, 20.0), (30.0, 40.0)]
            )
            self.assertEqual(
                backend.config.FALLBACK_COORDINATES,
                [(10.0, 20.0), (30.0, 40.0)]
            )
            # The newly configured coordinate (10.0, 20.0) should now be identified as fallback
            self.assertTrue(data_acquisition.geo_config.is_fallback_coordinate(10.0, 20.0))
            self.assertFalse(backend.utils.validators._check_has_pin({
                "lat": 10.0,
                "lng": 20.0,
                "address": "Generic Overridden City Hub"
            }))
            # The old default coordinate (12.9716, 77.5946) is no longer in FALLBACK_COORDINATES
            self.assertFalse(data_acquisition.geo_config.is_fallback_coordinate(12.9716, 77.5946))
            self.assertTrue(backend.utils.validators._check_has_pin({
                "lat": 12.9716,
                "lng": 77.5946,
                "address": "Specific MG Road Pin, Bengaluru"
            }))

    def test_override_generic_hub_labels_behavior(self):
        env_patch = {
            "GENERIC_HUB_LABELS": "hyderabad hub,secunderabad"
        }
        with mock.patch.dict(os.environ, env_patch):
            importlib.reload(backend.config)
            importlib.reload(backend.utils.validators)
            self.assertIn("hyderabad hub", backend.config.GENERIC_HUB_LABELS)
            self.assertFalse(backend.utils.validators._check_has_pin({
                "lat": 17.4,
                "lng": 78.4,
                "city": "hyderabad hub"
            }))


if __name__ == '__main__':
    unittest.main(verbosity=2)
