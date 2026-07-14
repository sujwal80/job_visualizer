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
    logo_enricher = LogoEnricher()
    location_enricher = LocationEnricher(db)

    db.load_db()
    
    # 1. Tagging/Enrichment Loop
    processed = 0
    for startup in db.startups:
        if not args.force and startup.get("tagging_status") == "completed":
            print(f"[Tagging] Skipping {startup.get('name')} - already completed.")
            continue

        if args.max_tagging is not None and processed >= args.max_tagging:
            print(f"[Tagging] Reached max-tagging limit of {args.max_tagging}")
            break

        print(f"[Tagging] Processing company: '{startup.get('name')}'")
        try:
            logo_changed = logo_enricher.enrich(startup)
            loc_changed = location_enricher.enrich(startup, target_city=args.target_city)
            startup["tagging_status"] = "completed"
            processed += 1
        except Exception as e:
            print(f"[Tagging] Error enriching '{startup.get('name')}': {e}")
            startup["tagging_status"] = "failed"

    # 2. Industry Classification Loop
    classified = 0
    for startup in db.startups:
        if not args.force and startup.get("classification_status") == "completed":
            print(f"[Classification] Skipping {startup.get('name')} - already completed.")
            continue

        print(f"[Classification] Classifying company: '{startup.get('name')}'")
        try:
            new_ind = classify_startup(startup, force=args.force)
            startup["industry"] = new_ind
            startup["classification_status"] = "completed"
            classified += 1
        except Exception as e:
            print(f"[Classification] Error classifying '{startup.get('name')}': {e}")
            startup["classification_status"] = "failed"

    db.save_db()
    print(f"[Tagging & Classification Completed] Tagged: {processed}, Classified: {classified}")

if __name__ == "__main__":
    main()
