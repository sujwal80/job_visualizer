#!/usr/bin/env python3
"""
City-Address Consistency Verifier & Cleaner
Path: data_acquisition/verify_city_address_consistency.py

Enforces 100% consistency across city, office_address, and coordinates (lat, lng):
1. Removes cross-city address contamination (e.g., an address mentioning Hyderabad when the city is Mumbai).
2. Ensures coordinates always fall within the geographic bounding box of the company's designated city.
"""

import json
import os
import shutil
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.db_manager import DBManager

CITY_BOUNDS = {
    "Mumbai": {"lat": (18.8, 19.4), "lng": (72.7, 73.1), "default": (19.0760, 72.8777)},
    "Bengaluru": {"lat": (12.8, 13.2), "lng": (77.4, 77.8), "default": (12.9716, 77.5946)},
    "Hyderabad": {"lat": (17.2, 17.6), "lng": (78.3, 78.7), "default": (17.3850, 78.4867)},
    "Chennai": {"lat": (12.8, 13.2), "lng": (80.1, 80.4), "default": (13.0827, 80.2707)},
    "Kolkata": {"lat": (22.4, 22.7), "lng": (88.2, 88.5), "default": (22.5726, 88.3639)},
    "Pune": {"lat": (18.4, 18.7), "lng": (73.7, 74.0), "default": (18.5204, 73.8567)},
    "Delhi": {"lat": (28.4, 28.9), "lng": (77.0, 77.4), "default": (28.6139, 77.2090)}
}

def get_base_city(city_label):
    c = str(city_label).lower() if city_label else ""
    if "mumbai" in c: return "Mumbai"
    if "kolkata" in c: return "Kolkata"
    if "chennai" in c: return "Chennai"
    if "hyderabad" in c: return "Hyderabad"
    if "pune" in c: return "Pune"
    if "delhi" in c or "ncr" in c or "gurugram" in c or "gurgaon" in c or "noida" in c: return "Delhi"
    return "Bengaluru"

def main():
    db_path = os.path.join(PROJECT_ROOT, "backend", "startups.json")
    public_db_path = os.path.join(PROJECT_ROOT, "public", "static", "data", "startups.json")

    print(f"=== ENFORCING CITY-ADDRESS-COORDINATE CONSISTENCY IN {db_path} ===")
    with open(db_path, "r") as f:
        startups = json.load(f)

    fixed_addresses = 0
    fixed_coords = 0

    for s in startups:
        city_raw = str(s.get("city") or "Bengaluru")
        base_city = get_base_city(city_raw)
        addr = str(s.get("office_address") or "")

        # 1. Check if office_address mentions a conflicting city or conflicting neighborhood
        other_cities = [c for c in CITY_BOUNDS.keys() if c != base_city]
        blr_localities = [
            "yemalur", "yemaluru", "koramangala", "indiranagar", "whitefield", "hsr",
            "ecospace", "marathahalli", "devarabeesanahalli", "kadubeesanahalli", "bagmane",
            "embassy", "old madras road", "bellandur", "jayanagar", "jp nagar"
        ]
        has_conflict = any(oc.lower() in addr.lower() for oc in other_cities)
        if base_city != "Bengaluru" and not has_conflict:
            has_conflict = any(loc in addr.lower() for loc in blr_localities)

        if has_conflict:
            s["office_address"] = f"{base_city}, India"
            s["bangalore_address"] = f"{base_city}, India"
            fixed_addresses += 1

        # 2. Check if coordinates fall outside the bounding box of base_city
        lat = s.get("lat")
        lng = s.get("lng")
        bounds = CITY_BOUNDS.get(base_city, CITY_BOUNDS["Bengaluru"])
        in_bounds = (
            lat is not None and lng is not None and
            bounds["lat"][0] <= lat <= bounds["lat"][1] and
            bounds["lng"][0] <= lng <= bounds["lng"][1]
        )

        if not in_bounds:
            s["lat"] = bounds["default"][0]
            s["lng"] = bounds["default"][1]
            fixed_coords += 1

    with open(db_path, "w") as f:
        json.dump(startups, f, indent=2)

    shutil.copy2(db_path, public_db_path)
    print(f"✅ CONSISTENCY AUDIT COMPLETED!")
    print(f"   Fixed cross-city address contamination : {fixed_addresses}")
    print(f"   Fixed out-of-bounds coordinates        : {fixed_coords}")
    print(f"   Synchronized {db_path} -> {public_db_path}")

if __name__ == "__main__":
    main()
