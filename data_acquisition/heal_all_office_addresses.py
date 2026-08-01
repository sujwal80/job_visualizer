#!/usr/bin/env python3
"""
Real-World Office Address Enricher & Healer
Path: data_acquisition/heal_all_office_addresses.py

Populates real-world street/building addresses for all startups in startups.json
whose `office_address` is currently just a generic city name (Bengaluru, Mumbai, etc.).
"""

import json
import os
import re
import shutil
import sys
import time
import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.db_manager import DBManager

def get_osm_street_address(name, city):
    url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": "BangaloreStartupVisualizer/1.0 (contact: info@startupvisualizer.com)"}
    queries = [f"{name}, {city}", f"{name} office, {city}", f"{name}, India"]
    for q in queries:
        try:
            res = requests.get(url, params={"q": q, "format": "json", "limit": 1}, headers=headers, timeout=5)
            data = res.json()
            if data and "display_name" in data[0]:
                disp = data[0]["display_name"]
                # Clean up display name
                parts = [p.strip() for p in disp.split(",") if p.strip()]
                if len(parts) >= 2:
                    return ", ".join(parts[:4])
                return disp
        except Exception:
            pass
        time.sleep(1.0)
    return None


def get_address_from_jobs(jobs):
    for j in jobs:
        if isinstance(j, dict):
            loc = str(j.get("location") or "").strip()
            if any(w in loc.lower() for w in [
                "road", "rd", "street", "st", "park", "layout", "nagar", "tower",
                "building", "floor", "block", "sector", "phase", "campus", "centre",
                "center", "hub", "complex", "midc", "sez", "area", "estate",
                "whitefield", "hsr", "koramangala", "indiranagar", "ecospace", "bkc"
            ]):
                return loc
    return None


def main():
    db_path = os.path.join(PROJECT_ROOT, "backend", "startups.json")
    public_db_path = os.path.join(PROJECT_ROOT, "public", "static", "data", "startups.json")

    print(f"=== ENRICHING REAL-WORLD OFFICE ADDRESSES IN {db_path} ===")
    with open(db_path, "r") as f:
        startups = json.load(f)

    enriched_count = 0
    for s in startups:
        addr = str(s.get("office_address") or "").strip()
        city = str(s.get("city") or "").strip()
        name = s["name"]

        is_generic = (
            not addr
            or addr.lower() in [
                city.lower(), "bengaluru", "bangalore", "mumbai", "hyderabad",
                "chennai", "pune", "kolkata", "delhi", "delhi ncr", "india", "in",
                "n/a", "bangalore, in", "bengaluru, karnataka, india", ""
            ]
        )

        if is_generic:
            # Try job postings first for explicit street address
            job_addr = get_address_from_jobs(s.get("job_openings", []))
            if job_addr:
                s["office_address"] = job_addr
                s["bangalore_address"] = job_addr
                enriched_count += 1
                continue

            # Try OSM display_name
            osm_addr = get_osm_street_address(name, city)
            if osm_addr:
                s["office_address"] = osm_addr
                s["bangalore_address"] = osm_addr
                enriched_count += 1
                print(f"[Address Enriched] {name:25s} ({city}) -> {osm_addr}")

    with open(db_path, "w") as f:
        json.dump(startups, f, indent=2)

    shutil.copy2(db_path, public_db_path)
    print(f"\n✅ OFFICE ADDRESS ENRICHMENT COMPLETED!")
    print(f"   Startups enriched with real street/building address : {enriched_count}")
    print(f"   Synchronized {db_path} -> {public_db_path}")


if __name__ == "__main__":
    main()
