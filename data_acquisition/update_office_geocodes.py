#!/usr/bin/env python3
"""
Script to get lat & long data from each full address of each office and update
that lat & long EXCLUSIVELY for that office in startups.json.
Path: data_acquisition/update_office_geocodes.py
"""

import os
import sys
import json
import time
import shutil
import re
import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.db_manager import DBManager

def is_valid_for_region(lat, lng, city, address):
    """Validate that coordinates match expected geographic bounding boxes (e.g., India)."""
    text = f"{city} {address}".lower()
    indian_keywords = [
        "india", "bengaluru", "bangalore", "mumbai", "delhi", "hyderabad", "pune", "chennai", "kolkata",
        "gurgaon", "gurugram", "noida", "karnataka", "maharashtra", "telangana", "tamil nadu", "west bengal", "haryana", "uttar pradesh"
    ]
    if any(kw in text for kw in indian_keywords):
        # India rough bounding box: Lat 6°N to 37°N, Lng 68°E to 98°E
        if not (6.0 <= lat <= 37.0 and 68.0 <= lng <= 98.0):
            return False
    return True

def geocode_with_fallbacks(db, address, company_name, city, cache):
    norm_addr = address.lower().strip()
    if norm_addr in cache:
        c_lat, c_lng = cache[norm_addr][0], cache[norm_addr][1]
        if is_valid_for_region(c_lat, c_lng, city, address):
            return c_lat, c_lng

    # Attempt 1: Full address via DBManager
    lat, lng = db.geocode_address(address, company_name=company_name, target_city=city)
    if lat is not None and lng is not None and is_valid_for_region(lat, lng, city, address):
        cache[norm_addr] = [lat, lng]
        return lat, lng

    # Attempt 2: Strip floor/room/suite/door details and re-query
    simplified = re.sub(r'\b(?:no\.|number|flat|door|unit|suite|room|cabin|floor|flr|plot|bldg|building|tower|wing)\s*[\w\d\-\/\&]+\b', '', address, flags=re.I)
    simplified = re.sub(r'\s+', ' ', simplified).strip(' ,.-')
    if simplified and simplified != address and len(simplified) > 5:
        lat, lng = db.geocode_address(simplified, company_name=company_name, target_city=city)
        if lat is not None and lng is not None and is_valid_for_region(lat, lng, city, address):
            cache[norm_addr] = [lat, lng]
            return lat, lng

    # Attempt 3: Query using just the latter half (locality + city + state)
    parts = [p.strip() for p in address.split(',') if p.strip()]
    if len(parts) >= 2:
        latter_half = ", ".join(parts[-2:])
        lat, lng = db.geocode_address(latter_half, company_name=None, target_city=city)
        if lat is not None and lng is not None and is_valid_for_region(lat, lng, city, address):
            cache[norm_addr] = [lat, lng]
            return lat, lng

    return None, None

def run_update():
    db_path = os.path.join(PROJECT_ROOT, "backend", "startups.json")
    print(f"Loading startups from {db_path}...")
    with open(db_path, "r") as f:
        data = json.load(f)

    # Clean any accidental root-level lat/lng if present
    for s in data:
        s.pop("lat", None)
        s.pop("lng", None)

    db = DBManager(db_path=db_path)
    db.load_db()
    
    cache_path = os.path.join(PROJECT_ROOT, "data_acquisition", "cache", "geocode_cache.json")
    cache = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    total_offices = sum(len(s.get("offices", [])) for s in data)
    print(f"Starting geocode update for {total_offices} total offices across {len(data)} companies...")

    updated_count = 0
    checked_count = 0

    for idx, startup in enumerate(data):
        s_name = startup.get("name", "Unknown")
        offices = startup.get("offices", [])
        for o_idx, o in enumerate(offices):
            checked_count += 1
            addr = o.get("office_address") or o.get("city") or ""
            city = o.get("city", "")
            old_lat = o.get("lat")
            old_lng = o.get("lng")

            print(f"\n[{checked_count}/{total_offices}] Company: '{s_name}' | Office: '{addr}'")
            new_lat, new_lng = geocode_with_fallbacks(db, addr, s_name, city, cache)
            
            if new_lat is not None and new_lng is not None:
                if old_lat != new_lat or old_lng != new_lng:
                    o["lat"] = round(new_lat, 7)
                    o["lng"] = round(new_lng, 7)
                    o["location_tagged"] = True
                    updated_count += 1
                    print(f"  -> Updated Office Coordinates: ({old_lat}, {old_lng}) => ({o['lat']}, {o['lng']})")
                else:
                    print(f"  -> Office Coordinates verified unchanged: ({o['lat']}, {o['lng']})")
            else:
                print(f"  -> Could not geocode address reliably. Retaining previous coordinates: ({old_lat}, {old_lng})")

        # Periodically save cache and database every 20 startups
        if (idx + 1) % 20 == 0:
            with open(db_path, "w") as f:
                json.dump(data, f, indent=2)
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w") as f:
                json.dump(cache, f, indent=2)

    # Final save of database and cache
    with open(db_path, "w") as f:
        json.dump(data, f, indent=2)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2)

    print(f"\n=== Geocoding Complete ===")
    print(f"Checked {checked_count} offices. Updated coordinates for {updated_count} offices.")

    # Synchronize database to public folder for frontend
    public_db_path = os.path.join(PROJECT_ROOT, "public", "static", "data", "startups.json")
    os.makedirs(os.path.dirname(public_db_path), exist_ok=True)
    shutil.copy2(db_path, public_db_path)
    print(f"Synchronized database to: {public_db_path}")

if __name__ == "__main__":
    run_update()
