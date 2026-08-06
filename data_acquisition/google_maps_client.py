#!/usr/bin/env python3
"""
Ultra-Efficient Google Maps Geocoding Client with Persistent Caching & Monthly Quota Protection
Path: data_acquisition/google_maps_client.py
"""

import os
import sys
import json
import time
import re
import datetime
import requests
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

CACHE_DIR = os.path.join(PROJECT_ROOT, "data_acquisition", "cache")
CACHE_FILE = os.path.join(CACHE_DIR, "google_maps_cache.json")
QUOTA_FILE = os.path.join(CACHE_DIR, "google_quota_tracker.json")

# Maximum requests allowed per calendar month (Safety buffer below free 10k/40k threshold)
DEFAULT_MONTHLY_LIMIT = 8500 

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOG")

# In-memory caches
_CACHE = {}
_CACHE_LOADED = False
_QUOTA_TRACKER = {}

def _init_cache():
    global _CACHE, _CACHE_LOADED, _QUOTA_TRACKER
    if _CACHE_LOADED:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _CACHE = json.load(f)
        except Exception:
            _CACHE = {}
    if os.path.exists(QUOTA_FILE):
        try:
            with open(QUOTA_FILE, "r", encoding="utf-8") as f:
                _QUOTA_TRACKER = json.load(f)
        except Exception:
            _QUOTA_TRACKER = {}
    _CACHE_LOADED = True

def _save_cache():
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_CACHE, f, indent=2)
    except Exception as e:
        print(f"[Cache Error] Failed to persist cache: {e}")

def _save_quota():
    try:
        with open(QUOTA_FILE, "w", encoding="utf-8") as f:
            json.dump(_QUOTA_TRACKER, f, indent=2)
    except Exception as e:
        print(f"[Quota Error] Failed to persist quota: {e}")

def normalize_address(address):
    """Normalize address string to maximize cache hit rate."""
    if not address:
        return ""
    addr = str(address).strip().lower()
    # Normalize multiple spaces, tabs, newlines
    addr = re.sub(r'[\r\n\t]+', ' ', addr)
    addr = re.sub(r'\s+', ' ', addr)
    addr = addr.strip(' ,.-')
    return addr

def get_current_month_key():
    return datetime.datetime.utcnow().strftime("%Y-%m")

def get_monthly_usage():
    _init_cache()
    month_key = get_current_month_key()
    return _QUOTA_TRACKER.get(month_key, 0)

def record_api_call():
    _init_cache()
    month_key = get_current_month_key()
    _QUOTA_TRACKER[month_key] = _QUOTA_TRACKER.get(month_key, 0) + 1
    _save_quota()
    return _QUOTA_TRACKER[month_key]

def is_generic_or_empty(address):
    """Avoid making API calls on purely generic city names or blank inputs."""
    norm = normalize_address(address)
    if len(norm) < 4:
        return True
    generic = {
        "mumbai", "mumbai, maharashtra", "bengaluru", "bengaluru, karnataka", "bangalore",
        "hyderabad", "hyderabad, telangana", "pune", "pune, maharashtra",
        "chennai", "chennai, tamil nadu", "kolkata", "kolkata, west bengal",
        "delhi", "new delhi", "new delhi, delhi", "delhi ncr", "gurugram", "noida", "india"
    }
    if norm in generic:
        return True
    # If no numbers and less than 15 chars, likely generic area without street details
    if len(norm) < 15 and not any(ch.isdigit() for ch in norm):
        return True
    return False

def get_google_geocode(address, api_key=None, monthly_limit=DEFAULT_MONTHLY_LIMIT):
    """
    Ultra-safe Geocode lookup with caching and quota enforcement.
    Returns (lat, lng) or (None, None).
    """
    _init_cache()
    key = api_key or GOOGLE_MAPS_API_KEY
    if not key:
        return None, None

    norm = normalize_address(address)
    if not norm or is_generic_or_empty(norm):
        return None, None

    # Step 1: Check In-Memory / On-Disk Cache (0 API calls, Instant)
    if norm in _CACHE:
        cached_val = _CACHE[norm]
        if cached_val is None:
            return None, None
        return cached_val[0], cached_val[1]

    # Step 2: Check Monthly Safety Quota
    current_calls = get_monthly_usage()
    if current_calls >= monthly_limit:
        print(f"⚠️ [Google Maps Quota Guard] Monthly limit of {monthly_limit} reached ({current_calls} calls this month). Skipping API request.")
        return None, None

    # Step 3: Execute Google Maps API Request
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": norm,
        "key": key,
        "components": "country:IN"
    }

    try:
        resp = requests.get(url, params=params, timeout=6)
        # Record the call in our persistent tracker
        new_count = record_api_call()
        print(f"  [Google Maps API Call #{new_count}/{monthly_limit}] Query: '{norm[:50]}'")

        data = resp.json()
        status = data.get("status")

        if status == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            lat = round(float(loc["lat"]), 7)
            lng = round(float(loc["lng"]), 7)
            if 6.0 <= lat <= 37.0 and 68.0 <= lng <= 98.0:
                _CACHE[norm] = [lat, lng]
                _save_cache()
                return lat, lng
            else:
                _CACHE[norm] = None
                _save_cache()
                return None, None
        elif status == "ZERO_RESULTS":
            # Negative cache: store None so we NEVER request this unresolvable string again
            _CACHE[norm] = None
            _save_cache()
            return None, None
        elif status in ("OVER_QUERY_LIMIT", "REQUEST_DENIED"):
            print(f"⚠️ [Google Maps API Response] Status: {status} - {data.get('error_message')}")
            return None, None
    except Exception as e:
        print(f"⚠️ [Google Maps API Error]: {e}")

    return None, None

def print_quota_summary():
    _init_cache()
    month_key = get_current_month_key()
    usage = _QUOTA_TRACKER.get(month_key, 0)
    cached_count = len(_CACHE)
    print("\n" + "="*50)
    print("🗺️  GOOGLE MAPS GEOCODING QUOTA & CACHE SUMMARY")
    print("="*50)
    print(f"Month:              {month_key}")
    print(f"Total API Calls:    {usage} / {DEFAULT_MONTHLY_LIMIT} (Budget Cap)")
    print(f"Cached Addresses:   {cached_count} entries in {os.path.basename(CACHE_FILE)}")
    print(f"Remaining Safe API: {max(0, DEFAULT_MONTHLY_LIMIT - usage)} requests")
    print("="*50 + "\n")

if __name__ == "__main__":
    print_quota_summary()
