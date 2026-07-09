"""
Centralized Geographic & Scraper Configuration Module
Provides configurable defaults and helper functions for geographic coordinates,
fallbacks, city synonyms, and domain settings across data acquisition modules.
"""

import os
import re

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
        "bengaluru, karnataka", "hyderabad", "mumbai", "delhi",
        "pune", "chennai", "gurugram", "gurgaon", "noida", "new delhi",
        "in", "ncr", "united states", "usa", "us", "united kingdom",
        "uk", "europe", "remote", "global", "worldwide", "anywhere"
    }

# Nationwide India locations and synonyms
INDIA_SYNONYMS = [
    "india", "in",
    "bengaluru", "bangalore",
    "hyderabad",
    "mumbai", "bombay",
    "delhi", "new delhi", "ncr",
    "gurugram", "gurgaon",
    "noida",
    "pune",
    "chennai", "madras",
    "ahmedabad",
    "kolkata", "calcutta",
    "jaipur",
    "kochi", "cochin",
    "indore",
    "chandigarh",
    "coimbatore",
    "karnataka",
    "maharashtra",
    "telangana",
    "tamil nadu",
    "kerala",
    "gujarat",
    "rajasthan",
    "west bengal",
    "punjab",
    "haryana",
    "uttar pradesh",
    "odisha",
    "bihar",
    "assam",
    "surat",
    "vadodara",
    "nagpur",
    "bhopal",
    "visakhapatnam",
    "thiruvananthapuram",
    "mysuru", "mysore",
    "mangalore"
]

USA_SYNONYMS = [
    "united states", "usa", "us", "san francisco", "sf", "bay area", "new york", "nyc",
    "austin", "seattle", "boston", "los angeles", "la", "chicago"
]

UK_SYNONYMS = [
    "united kingdom", "uk", "london", "manchester", "cambridge", "oxford"
]

# City synonyms for matching target cities across scrapers and enrichers
CITY_SYNONYMS = {
    "bengaluru": ["bengaluru", "bangalore"],
    "bangalore": ["bengaluru", "bangalore"],
    "hyderabad": ["hyderabad"],
    "mumbai": ["mumbai", "bombay"],
    "delhi": ["delhi", "new delhi", "ncr", "gurugram", "gurgaon", "noida"],
    "gurugram": ["gurugram", "gurgaon", "delhi", "new delhi", "ncr"],
    "gurgaon": ["gurugram", "gurgaon", "delhi", "new delhi", "ncr"],
    "noida": ["noida", "delhi", "new delhi", "ncr"],
    "pune": ["pune"],
    "chennai": ["chennai", "madras"],
    "india": INDIA_SYNONYMS,
    "in": INDIA_SYNONYMS,
    "san francisco": ["san francisco", "sf", "bay area"],
    "new york": ["new york", "nyc"],
    "london": ["london", "uk"],
    "united states": USA_SYNONYMS,
    "usa": USA_SYNONYMS,
    "us": USA_SYNONYMS,
    "united kingdom": UK_SYNONYMS,
    "uk": UK_SYNONYMS,
}

# Canonical multi-city center coordinates mapping (lat, lng)
MULTI_CITY_CENTERS = {
    "bengaluru": (12.9716, 77.5946),
    "bangalore": (12.9716, 77.5946),
    "delhi": (28.6139, 77.2090),
    "new delhi": (28.6139, 77.2090),
    "ncr": (28.6139, 77.2090),
    "gurugram": (28.4595, 77.0266),
    "gurgaon": (28.4595, 77.0266),
    "noida": (28.5355, 77.3910),
    "hyderabad": (17.3850, 78.4867),
    "mumbai": (19.0760, 72.8777),
    "bombay": (19.0760, 72.8777),
    "pune": (18.5204, 73.8567),
    "chennai": (13.0827, 80.2707),
    "madras": (13.0827, 80.2707),
    "kolkata": (22.5726, 88.3639),
    "calcutta": (22.5726, 88.3639),
    "ahmedabad": (23.0225, 72.5714),
    "singapore": (1.3521, 103.8198),
    "california": (37.7749, -122.4194),
    "san francisco": (37.7749, -122.4194),
    "sf": (37.7749, -122.4194),
    "bay area": (37.7749, -122.4194),
    "london": (51.5074, -0.1278),
    "new york": (40.7128, -74.0060),
    "nyc": (40.7128, -74.0060),
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


def _keyword_matches(keyword, loc_lower):
    kw = str(keyword).lower().strip()
    if not kw:
        return False
    if kw == "in":
        return bool(re.search(r'\bin\b', loc_lower))
    return kw in loc_lower


def match_target_city(location, target_city):
    """
    Match whether a location string corresponds to the target city or any of its synonyms.
    Supports global/worldwide targets where any location is accepted.
    """
    if not location or not target_city:
        return False
    loc_lower = str(location).lower()
    target_lower = str(target_city).lower().strip()

    # Global / Worldwide / Remote wildcard target
    if target_lower in ["global", "worldwide", "any", "all", "remote"]:
        return True

    # If target is nationwide India / IN
    if target_lower in ["india", "in"]:
        if _keyword_matches("in", loc_lower):
            return True
        return any(k in loc_lower for k in INDIA_SYNONYMS if k != "in")

    # Direct keyword match
    if _keyword_matches(target_lower, loc_lower):
        return True

    # Synonym matching
    synonyms = CITY_SYNONYMS.get(target_lower, [target_lower])
    for syn in synonyms:
        if _keyword_matches(syn, loc_lower):
            return True
    return False


def get_city_center_coordinates(target_city):
    """
    Get the (lat, lng) city center coordinates for a target city.
    Returns None if target_city is None, a global/worldwide query, or not found.
    """
    if target_city is None:
        return None
    t_lower = str(target_city).strip().lower()
    if not t_lower or t_lower in {
        "india", "in", "worldwide", "global", "remote", "any", "all", "anywhere",
        "united states", "usa", "us", "united kingdom", "uk", "europe"
    }:
        return None

    if t_lower in MULTI_CITY_CENTERS:
        return MULTI_CITY_CENTERS[t_lower]

    if t_lower in CITY_SYNONYMS:
        for syn in CITY_SYNONYMS[t_lower]:
            syn_lower = syn.strip().lower()
            if syn_lower in MULTI_CITY_CENTERS:
                return MULTI_CITY_CENTERS[syn_lower]

    for canonical, syns in CITY_SYNONYMS.items():
        if t_lower in [s.lower() for s in syns]:
            if canonical in MULTI_CITY_CENTERS:
                return MULTI_CITY_CENTERS[canonical]
            for syn in syns:
                if syn.lower() in MULTI_CITY_CENTERS:
                    return MULTI_CITY_CENTERS[syn.lower()]

    return None


def get_mock_jobs(source="Mock", keywords="Software", target_city=None, company_name=None):
    """
    Generate high-quality deterministic mock/fixture job openings matching the target city
    for testing or fallback when live scrapers are rate-limited or blocked.
    """
    if target_city is None:
        target_city = DEFAULT_TARGET_CITY
    kw = str(keywords or "Software Engineer").strip()
    c_name = str(company_name or f"{target_city} Innovation Labs").strip()
    slug_kw = re.sub(r'[^a-z0-9]+', '-', kw.lower()).strip('-') or "role"
    slug_comp = re.sub(r'[^a-z0-9]+', '-', c_name.lower()).strip('-') or "comp"
    source_slug = re.sub(r'[^a-z0-9]+', '-', str(source).lower()).strip('-') or "mock"
    return [
        {
            "title": f"Senior {kw} Specialist",
            "company_name": c_name,
            "company_slug": slug_comp,
            "job_url": f"https://www.google.com/jobs/{source_slug}-{slug_comp}-1",
            "url": f"https://www.google.com/jobs/{source_slug}-{slug_comp}-1",
            "location": str(target_city),
            "source": str(source),
            "experience": "3-5 years",
            "salary": "20-30 LPA",
            "job_type": "Full-time",
            "skills": ["Python", "Cloud", "Architecture"],
            "posted_date": "1 day ago"
        }
    ]
