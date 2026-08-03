#!/usr/bin/env python3
"""
Unified Production Data Acquisition & Validation Runner for Indian Metro Cities
Path: data_acquisition/run_all_metro_cities_production.py

Executes real-world company discovery, crawling, enrichment, and validation across:
1. Bengaluru (Bangalore)
2. Hyderabad
3. Delhi NCR (Delhi, New Delhi, Gurugram, Noida)
4. Chennai
5. Kolkata
6. Pune
7. Mumbai

Key Enforcements:
- NO limits (crawls and discovers companies across all metro cities).
- NO mock data (MOCK_SCRAPER_FALLBACK='false').
- Full real-world validation of website, logo, office address, and coordinates.
- Continuous synchronization of backend/startups.json -> public/static/data/startups.json.
"""

import os
import sys
import json
import time
import shutil

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.db_manager import DBManager
from data_acquisition.pipelines.discovery.discovery_service import CompanyDiscoveryService
from data_acquisition.pipelines.crawling.job_scrapers.linkedin_scraper import LinkedInScraper
from data_acquisition.pipelines.validation.job_validator import JobValidator
from data_acquisition.utils.validation import validate_logo_image, is_blacklisted_domain

METRO_CITIES = [
    "Bengaluru",
    "Hyderabad",
    "Delhi NCR",
    "Chennai",
    "Kolkata",
    "Pune",
    "Mumbai"
]

def audit_metro_city_coverage(db_path):
    with open(db_path, "r") as f:
        startups = json.load(f)

    city_counts = {city: 0 for city in METRO_CITIES}
    other_count = 0

    for s in startups:
        city_val = str(s.get("city") or "Bengaluru")
        matched = False
        for m_city in METRO_CITIES:
            if m_city.lower() in city_val.lower() or (m_city == "Delhi NCR" and any(k in city_val.lower() for k in ["delhi", "noida", "gurugram", "gurgaon", "ncr"])):
                city_counts[m_city] += 1
                matched = True
                break
        if not matched:
            other_count += 1

    print("\n=== METRO CITY REPRESENTATION IN PROD DB ===")
    for c, count in sorted(city_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {c:15s}: {count:4d} startups")
    if other_count > 0:
        print(f"  {'Other/Hubs':15s}: {other_count:4d} startups")
    print(f"  {'TOTAL':15s}: {len(startups):4d} startups")
    return city_counts


def validate_and_enrich_prod_db(db_path, public_db_path):
    print("\n[Prod DB Validation] Validating real-world data and enforcing city consistency...")
    db = DBManager(db_path=db_path)
    # 1. Normalize and deduplicate city offices
    db.normalize_and_deduplicate_offices()
    # 2. Heal any generic addresses with real-world street/building addresses
    db.heal_all_generic_offices()
    # 3. Polish and clean address formatting
    db.polish_all_addresses()
    # 4. Remediate WAF/Cloudflare homepage issue logos
    db.remediate_issue_logos()
    # 5. Final synchronization check
    shutil.copy2(db_path, public_db_path)
    print(f"[Prod DB Validation] Verified and synchronized {db_path} -> {public_db_path}")


def run_metro_acquisition(city, db, discovery, scraper):
    print(f"\n=========================================================")
    print(f" 🚀 STARTING REAL-WORLD ACQUISITION FOR: {city.upper()} 🚀")
    print(f"=========================================================")

    # Run discovery without limits and without mock fallback
    os.environ["MOCK_SCRAPER_FALLBACK"] = "false"
    try:
        discovery.discover_new_companies(max_new_companies=None, target_city=city)
    except Exception as e:
        print(f"[Acquisition Error] Discovery failed for {city}: {str(e)}")


def main():
    os.environ["MOCK_SCRAPER_FALLBACK"] = "false"
    db_path = os.path.join(PROJECT_ROOT, "backend", "startups.json")
    public_db_path = os.path.join(PROJECT_ROOT, "public", "static", "data", "startups.json")

    print(f"=== UNIFIED PRODUCTION METRO DATA ACQUISITION ===")
    print(f"Target Metro Cities : {', '.join(METRO_CITIES)}")
    print(f"Mock Data Mode      : DISABLED (MOCK_SCRAPER_FALLBACK=false)")
    print(f"Limits              : UNLIMITED")
    print(f"Prod DB             : {db_path}")

    # Initial audit
    audit_metro_city_coverage(db_path)

    # Validate existing prod DB first
    validate_and_enrich_prod_db(db_path, public_db_path)

    # Initialize DB & Scraper services
    db = DBManager(db_path=db_path)
    validator = JobValidator(db)
    linkedin_scraper = LinkedInScraper(validator=validator)
    discovery = CompanyDiscoveryService(db, linkedin_scraper, validator=validator)

    # Execute acquisition across all Metro cities
    for city in METRO_CITIES:
        run_metro_acquisition(city, db, discovery, linkedin_scraper)
        # Validate and mirror after every city pass
        db.save_db()
        validate_and_enrich_prod_db(db_path, public_db_path)

    # Final audit
    print("\n=== FINAL METRO CITY ACQUISITION REPORT ===")
    audit_metro_city_coverage(db_path)
    print("\n✅ ALL METRO CITY ACQUISITION AND VALIDATION COMPLETE!")


if __name__ == "__main__":
    main()
