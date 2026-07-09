"""
Centralized Configuration Module for Backend Services & Utilities
Provides configurable generic defaults for geographical fallback coordinates,
default viewport centers, regional synonyms, and hub thresholds.
"""

import os

# Default Target City
DEFAULT_TARGET_CITY = os.environ.get("DEFAULT_TARGET_CITY", "Bengaluru")

# Default Map Center Settings
DEFAULT_MAP_CENTER_LAT = float(os.environ.get("DEFAULT_MAP_CENTER_LAT", "12.9716"))
DEFAULT_MAP_CENTER_LNG = float(os.environ.get("DEFAULT_MAP_CENTER_LNG", "77.5946"))

# Fallback Coordinate Pairs (including Bangalore city hub coords)
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
        FALLBACK_COORDINATES = [(12.9716, 77.5946), (12.9767, 77.5900), (12.9767936, 77.590082)]
else:
    FALLBACK_COORDINATES = [
        (12.9716, 77.5946),
        (12.9767, 77.5900),
        (12.9767936, 77.590082)
    ]

PIN_DELTA_THRESHOLD = float(os.environ.get("PIN_DELTA_THRESHOLD", "0.008"))

# Generic hub / city labels that represent unpinned regional entries
_generic_hubs_env = os.environ.get("GENERIC_HUB_LABELS")
if _generic_hubs_env:
    GENERIC_HUB_LABELS = {x.strip().lower() for x in _generic_hubs_env.split(",") if x.strip()}
else:
    GENERIC_HUB_LABELS = {
        "bengaluru", "bangalore", "india", "karnataka",
        "bengaluru, karnataka", "hyderabad", "mumbai", "delhi"
    }

# Regional / Country Synonym Map
REGION_SYNONYM_MAP = {
    "usa": {"usa", "us", "united states", "america", "sf", "san francisco", "california", "bay area"},
    "uk": {"uk", "united kingdom", "england", "london", "gb", "great britain"},
    "india": {"india", "in", "bengaluru", "bangalore", "karnataka", "blr"}
}
