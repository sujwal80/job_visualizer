"""
Centralized Configuration Module for Backend Services & Utilities
Provides configurable generic defaults for geographical fallback coordinates,
default viewport centers, regional synonyms, and hub thresholds.
"""

import os
import json

def get_config_value(key, env=None, default=None):
    """
    Look up key in env first (dictionary lookup or attribute lookup),
    then fall back to os.environ or default.
    """
    if env is not None:
        try:
            if hasattr(env, "get"):
                val = env.get(key)
                if val is not None:
                    return val
        except Exception:
            pass
        try:
            if hasattr(env, key):
                val = getattr(env, key)
                if val is not None:
                    return val
        except Exception:
            pass
    return os.environ.get(key, default)

def parse_fallback_coordinates(val):
    if not val:
        return [(12.9716, 77.5946), (12.9767, 77.5900), (12.9767936, 77.590082)]
    if isinstance(val, list):
        return val
    coords = []
    for pair in val.split(";"):
        parts = pair.strip().split(",")
        if len(parts) == 2:
            try:
                coords.append((float(parts[0]), float(parts[1])))
            except ValueError:
                pass
    return coords or [(12.9716, 77.5946), (12.9767, 77.5900), (12.9767936, 77.590082)]

def parse_generic_hub_labels(val):
    if not val:
        return {
            "bengaluru", "bangalore", "india", "karnataka",
            "bengaluru, karnataka", "hyderabad", "mumbai", "delhi"
        }
    if isinstance(val, (set, list)):
        return {x.strip().lower() for x in val if isinstance(x, str) and x.strip()}
    return {x.strip().lower() for x in val.split(",") if x.strip()}

def parse_region_synonym_map(val):
    default_map = {
        "usa": {"usa", "us", "united states", "america", "sf", "san francisco", "california", "bay area", "ca"},
        "uk": {"uk", "united kingdom", "england", "london", "gb", "great britain"},
        "india": {"india", "in", "bengaluru", "bangalore", "karnataka", "blr"}
    }
    if not val:
        return default_map
    if isinstance(val, dict):
        return {k.lower(): set(v) for k, v in val.items()}
    try:
        _parsed = json.loads(val)
        return {k.lower(): set(v) for k, v in _parsed.items()}
    except Exception:
        return default_map

# Module-level configuration globals
DEFAULT_TARGET_CITY = None
DEFAULT_MAP_CENTER_LAT = None
DEFAULT_MAP_CENTER_LNG = None
FALLBACK_COORDINATES = None
PIN_DELTA_THRESHOLD = None
GENERIC_HUB_LABELS = None
REGION_SYNONYM_MAP = None
GOOGLE_REDIRECT_URI = None

def setup_config(env):
    """
    Dynamically update the module-level configuration globals using get_config_value.
    """
    global DEFAULT_TARGET_CITY, DEFAULT_MAP_CENTER_LAT, DEFAULT_MAP_CENTER_LNG
    global FALLBACK_COORDINATES, PIN_DELTA_THRESHOLD, GENERIC_HUB_LABELS, REGION_SYNONYM_MAP
    global GOOGLE_REDIRECT_URI

    DEFAULT_TARGET_CITY = get_config_value("DEFAULT_TARGET_CITY", env, "Bengaluru")
    
    try:
        DEFAULT_MAP_CENTER_LAT = float(get_config_value("DEFAULT_MAP_CENTER_LAT", env, "12.9716"))
    except ValueError:
        DEFAULT_MAP_CENTER_LAT = 12.9716

    try:
        DEFAULT_MAP_CENTER_LNG = float(get_config_value("DEFAULT_MAP_CENTER_LNG", env, "77.5946"))
    except ValueError:
        DEFAULT_MAP_CENTER_LNG = 77.5946

    FALLBACK_COORDINATES = parse_fallback_coordinates(get_config_value("FALLBACK_COORDINATES", env, None))

    try:
        PIN_DELTA_THRESHOLD = float(get_config_value("PIN_DELTA_THRESHOLD", env, "0.008"))
    except ValueError:
        PIN_DELTA_THRESHOLD = 0.008

    GENERIC_HUB_LABELS = parse_generic_hub_labels(get_config_value("GENERIC_HUB_LABELS", env, None))
    
    REGION_SYNONYM_MAP = parse_region_synonym_map(get_config_value("REGION_SYNONYM_MAP", env, None))

    GOOGLE_REDIRECT_URI = get_config_value("GOOGLE_REDIRECT_URI", env, "http://127.0.0.1:5001/api/auth/callback")

# Initialize with default environment variables on module load
setup_config(None)

