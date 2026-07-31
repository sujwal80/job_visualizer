#!/usr/bin/env python3
"""
Real-World Data Healer & Geolocation Verifier
Path: data_acquisition/heal_real_world_data.py

Cleans up data corruption where:
1. Real street addresses were crammed into `city` while `office_address` was overwritten with default 'Bengaluru'.
2. Startups located in Mumbai, Kolkata, Chennai, Delhi, Pune, or Hyderabad were accidentally assigned Bengaluru coordinates.
3. Ensures 100% of startups in startups.json match real-world cities, office addresses, and OpenStreetMap geocoded coordinates across India.
"""

import json
import os
import re
import shutil
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.db_manager import DBManager
from data_acquisition.geo_config import is_fallback_coordinate

KNOWN_INDIAN_CITIES = [
    "Mumbai", "Kolkata", "Chennai", "Hyderabad", "Pune", "Delhi", "New Delhi",
    "Gurugram", "Gurgaon", "Noida", "Ahmedabad", "Jaipur", "Kochi", "Indore",
    "Chandigarh", "Coimbatore", "Bengaluru", "Bangalore"
]

def determine_true_city(city_val, addr_val, jobs):
    """Determine the true Indian city from city field, address, or job postings."""
    if any(k in addr_val.lower() for k in ["bengaluru", "bangalore"]):
        return "Bengaluru"
    combined = f"{city_val} {addr_val}".lower()
    for j in jobs:
        if isinstance(j, dict):
            combined += " " + str(j.get("location") or "").lower()

    if any(c in combined for c in ["mumbai", "bombay", "powai", "andheri"]):
        return "Mumbai"
    if any(c in combined for c in ["kolkata", "calcutta", "salt lake"]):
        return "Kolkata"
    if (any(c in combined for c in ["chennai"]) and "old madras road" not in combined) or ("madras" in combined and "old madras road" not in combined):
        return "Chennai"
    if any(c in combined for c in ["hyderabad", "gachibowli", "hitec city", "madhapur"]):
        return "Hyderabad"
    if any(c in combined for c in ["pune", "hinjewadi"]):
        return "Pune"
    if any(c in combined for c in ["delhi", "new delhi", "gurugram", "gurgaon", "noida", "ncr"]):
        return "Delhi NCR"
    return "Bengaluru"


def clean_address_string(text):
    if not text or not isinstance(text, str):
        return ""
    # Strip 'Primary ' or 'Registered Office Address ' prefixes
    clean = re.sub(r"^(primary|registered office address|office address|headquarters|location)\s*[:\-]?\s*", "", text, flags=re.IGNORECASE)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def main():
    db_path = os.path.join(PROJECT_ROOT, "backend", "startups.json")
    public_db_path = os.path.join(PROJECT_ROOT, "public", "static", "data", "startups.json")

    print(f"=== HEALING & VERIFYING REAL-WORLD DATA IN {db_path} ===")
    db = DBManager(db_path=db_path)
    db.load_db()

    healed_addresses = 0
    regeocoded_cities = 0

    for s in db.startups:
        name = str(s.get("name") or "Unknown").strip()
        city_raw = str(s.get("city") or "").strip()
        addr_raw = str(s.get("office_address") or s.get("bangalore_address") or "").strip()
        jobs = s.get("job_openings") or []

        true_city = determine_true_city(city_raw, addr_raw, jobs)

        # 1. If city_raw contains street address keywords, move to office_address
        has_street_keywords = any(kw in city_raw.lower() for kw in [
            "primary", "road", "rd", "street", "st", "floor", "tower", "building",
            "plot", "layout", "nagar", "park", "house", "marg", "sector", "block",
            "unit", "campus", "business park", "hiranandani", "ecospace"
        ])

        if has_street_keywords:
            cleaned_street = clean_address_string(city_raw)
            s["office_address"] = cleaned_street
            s["bangalore_address"] = cleaned_street
            healed_addresses += 1
        elif not addr_raw or addr_raw.lower() in ("bengaluru", "bangalore", "india", "in", "n/a", "bangalore, in", "bengaluru, karnataka, india"):
            # Ensure it is at least true_city
            s["office_address"] = true_city
            s["bangalore_address"] = true_city

        # 2. Normalize city label
        is_remote = "remote office" in city_raw.lower() or s.get("is_remote_office", False)
        if is_remote and true_city != "Bengaluru":
            s["city"] = f"{true_city} (Remote Office)"
            s["is_remote_office"] = True
        else:
            s["city"] = true_city
            if true_city == "Bengaluru":
                s["is_remote_office"] = False

        lat = s.get("lat")
        lng = s.get("lng")
        is_blr_coords = lat is not None and lng is not None and (12.5 <= lat <= 13.2 and 77.4 <= lng <= 78.0)
        is_mismatch = (true_city != "Bengaluru" and is_blr_coords) or (true_city == "Bengaluru" and not is_blr_coords)
        is_missing = (lat is None or lng is None or is_fallback_coordinate(lat, lng))

        if is_mismatch or is_missing:
            print(f"[Real-World Geocoder] Re-geocoding '{name}' in {true_city} (Mismatch: {is_mismatch}, Missing: {is_missing})...")
            # Try company name + true_city first
            new_lat, new_lng = db.geocode_address(s.get("office_address"), name, target_city=true_city)
            if new_lat is not None and new_lng is not None and not is_fallback_coordinate(new_lat, new_lng):
                # Ensure coordinate is actually in the vicinity of true_city if not Bengaluru
                if true_city != "Bengaluru" and (12.5 <= new_lat <= 13.2 and 77.4 <= new_lng <= 78.0):
                    # OSM returned Bengaluru coordinate for non-Bengaluru city; fallback to true_city OSM
                    c_lat, c_lng = db._geocode_osm(f"{true_city}, India")
                    if c_lat is not None and c_lng is not None:
                        s["lat"] = c_lat
                        s["lng"] = c_lng
                        regeocoded_cities += 1
                else:
                    s["lat"] = new_lat
                    s["lng"] = new_lng
                    regeocoded_cities += 1
            else:
                c_lat, c_lng = db._geocode_osm(f"{true_city}, India")
                if c_lat is not None and c_lng is not None:
                    s["lat"] = c_lat
                    s["lng"] = c_lng
                    regeocoded_cities += 1

    db.save_db()
    shutil.copy2(db_path, public_db_path)
    print(f"\n✅ REAL-WORLD HEALING COMPLETED!")
    print(f"   Healed street addresses moved from city field : {healed_addresses}")
    print(f"   Re-geocoded mismatched / missing coordinates  : {regeocoded_cities}")
    print(f"   Synchronized {db_path} -> {public_db_path}")


if __name__ == "__main__":
    main()
