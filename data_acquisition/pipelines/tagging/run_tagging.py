#!/usr/bin/env python3
"""
Data Tagging & Enrichment Runner
Path: data_acquisition/pipelines/tagging/run_tagging.py
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.db_manager import DBManager
from data_acquisition.pipelines.tagging.logo_enricher import LogoEnricher
from data_acquisition.pipelines.tagging.location_enricher import LocationEnricher
from data_acquisition.pipelines.tagging.classify_industries import classify_startup
from data_acquisition.geo_config import DEFAULT_TARGET_CITY

def main():
    parser = argparse.ArgumentParser(description="Run Data Tagging, Location/Logo Enrichment, and Classification.")
    parser.add_argument("--db-path", default="backend/startups.json", help="Path to startup database JSON")
    parser.add_argument("--target-city", default=DEFAULT_TARGET_CITY, help="Target city for location geocoding")
    parser.add_argument("--max-tagging", type=int, default=None, help="Max startups to tag")
    parser.add_argument("--force", action="store_true", help="Force retagging and reclassification")
    args = parser.parse_args()

    db_path = args.db_path
    if not os.path.isabs(db_path):
        db_path = os.path.join(PROJECT_ROOT, db_path)

    db = DBManager(db_path=db_path)
    location_enricher = LocationEnricher(db)
    from data_acquisition.pipelines.crawling.job_scrapers.linkedin_scraper import LinkedInScraper
    from data_acquisition.run_data_enricher import enrich_startup_record
    import shutil

    linkedin_scraper = LinkedInScraper(validator=None)

    db.load_db()
    
    # 1. Tagging/Enrichment Loop
    processed = 0
    for startup in db.startups:
        if not args.force and startup.get("tagging_status") == "completed" and startup.get("logo_svg_url") and startup.get("website"):
            print(f"[Tagging] Skipping {startup.get('name')} - already completed.")
            continue

        if args.max_tagging is not None and processed >= args.max_tagging:
            print(f"[Tagging] Reached max-tagging limit of {args.max_tagging}")
            break

        print(f"[Tagging] Processing company: '{startup.get('name')}'")
        try:
            enrich_startup_record(startup, db, linkedin_scraper, location_enricher, args.target_city)
            processed += 1
        except Exception as e:
            print(f"[Tagging] Error enriching '{startup.get('name')}': {e}")
            startup["tagging_status"] = "failed"

    db.save_db()
    
    # Synchronize with public/static/data/startups.json
    public_db_path = os.path.join(PROJECT_ROOT, "public", "static", "data", "startups.json")
    os.makedirs(os.path.dirname(public_db_path), exist_ok=True)
    shutil.copy2(db_path, public_db_path)
    print(f"[Tagging & Classification Completed] Tagged & Enriched: {processed} startups. Synchronized to {public_db_path}")

if __name__ == "__main__":
    main()

