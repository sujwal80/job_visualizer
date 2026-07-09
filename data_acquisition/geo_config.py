"""
Centralized Geographic & Scraper Configuration Module
Provides configurable defaults and helper functions for geographic coordinates,
fallbacks, city synonyms, and domain settings across data acquisition modules.
"""

import os

# Default Target City
DEFAULT_TARGET_CITY = os.environ.get("DEFAULT_TARGET_CITY", "Bengaluru")

# Default Map Viewport Centers
DEFAULT_MAP_CENTER_LAT = float(os.environ.get("DEFAULT_MAP_CENTER_LAT", "12.9716"))
DEFAULT_MAP_CENTER_LNG = float(os.environ.get("DEFAULT_MAP_CENTER_LNG", "77.5946"))

# Fallback Coordinate Pairs (e.g. general city-level geocode results)
_fallback_coords_env = os.environ.get("FALLBACK_COORDINATES")
if _fallback_coords_env:
    FALLBACK_COORDINATES = []
    for pair in _fallback_coords_env.split(";"):
        parts = pair.strip().split(",")
        if len(parts) == 2:
            try:
                FALLBACK_COORDINATES.append((float(parts[0]), float(parts[1])))
            except ValueError:
                pass
    if not FALLBACK_COORDINATES:
        FALLBACK_COORDINATES = [(12.9716, 77.5946), (12.9767936, 77.590082)]
else:
    FALLBACK_COORDINATES = [
        (12.9716, 77.5946),
        (12.9767936, 77.590082)
    ]

# Epsilon tolerances for coordinate comparisons
FALLBACK_EPSILON = float(os.environ.get("FALLBACK_EPSILON", "0.0001"))
PIN_DELTA_THRESHOLD = float(os.environ.get("PIN_DELTA_THRESHOLD", "0.008"))

# Localities list for address matching
_localities_env = os.environ.get("GEO_LOCALITIES")
if _localities_env:
    DEFAULT_GEO_LOCALITIES = [loc.strip().lower() for loc in _localities_env.split(",") if loc.strip()]
else:
    DEFAULT_GEO_LOCALITIES = [
        "hsr", "koramangala", "indiranagar", "whitefield", "jp nagar",
        "jayanagar", "electronic city", "bellandur", "marathahalli",
        "sarjapur", "banashankari", "malleshwaram", "rajajinagar",
        "mg road", "brigade road", "cunningham road", "richmond town",
        "frazer town", "btm layout", "yelahanka", "hebbal", "domlur",
        "ulsoor", "kalyan nagar", "banaswadi", "basavanagudi",
        "sadashivanagar", "kammanahalli", "mahadevapura", "hitec city"
    ]

# Generic hub / city labels that do not constitute a specific street address pin
_generic_hubs_env = os.environ.get("GENERIC_HUB_LABELS")
if _generic_hubs_env:
    GENERIC_HUB_LABELS = {x.strip().lower() for x in _generic_hubs_env.split(",") if x.strip()}
else:
    GENERIC_HUB_LABELS = {
        "bengaluru", "bangalore", "india", "karnataka",
        "bengaluru, karnataka", "hyderabad", "mumbai", "delhi"
    }

# City synonyms for matching target cities across scrapers and enrichers
CITY_SYNONYMS = {
    "bengaluru": ["bengaluru", "bangalore"],
    "bangalore": ["bengaluru", "bangalore"],
    "hyderabad": ["hyderabad"],
    "mumbai": ["mumbai", "bombay"],
    "delhi": ["delhi", "new delhi"]
}

# Test fixture whitelisted URLs
TEST_FIXTURE_WHITELIST_URLS = [
    url.strip() for url in os.environ.get(
        "TEST_FIXTURE_WHITELIST_URLS",
        "https://www.google.com,http://www.google.com"
    ).split(",") if url.strip()
]

# Discovery service default keywords
DEFAULT_DISCOVERY_KEYWORDS = [
    kw.strip() for kw in os.environ.get(
        "DEFAULT_DISCOVERY_KEYWORDS",
        "Startup,AI Startup,SaaS Startup,Fintech Startup"
    ).split(",") if kw.strip()
]


def is_fallback_coordinate(lat, lng, epsilon=None):
    """
    Check if the given lat/lng match any of the fallback coordinates within epsilon tolerance.
    """
    if lat is None or lng is None:
        return False
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (ValueError, TypeError):
        return False

    eps = epsilon if epsilon is not None else FALLBACK_EPSILON
    for f_lat, f_lng in FALLBACK_COORDINATES:
        if abs(lat_f - f_lat) < eps and abs(lng_f - f_lng) < eps:
            return True
    return False


def match_target_city(location, target_city):
    """
    Match whether a location string corresponds to the target city or any of its synonyms.
    """
    if not location or not target_city:
        return False
    loc_lower = str(location).lower()
    target_lower = str(target_city).lower().strip()

    # Direct substring match
    if target_lower in loc_lower:
        return True

    # Synonym matching
    synonyms = CITY_SYNONYMS.get(target_lower, [target_lower])
    for syn in synonyms:
        if syn in loc_lower:
            return True
    return False
