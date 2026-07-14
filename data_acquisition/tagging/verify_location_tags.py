#!/usr/bin/env python3
"""
Batch Verification and Location Tagging Script

Iterates through company records in the startup database, verifies location coordinates,
classifies remote office status (`is_remote_office`), sanitizes floating-point attributes
against NaN/Infinity, and enforces idempotency (`location_tagged: True`).
"""

import argparse
import math
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
DATA_ACQ_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if DATA_ACQ_DIR not in sys.path:
    sys.path.insert(0, DATA_ACQ_DIR)

try:
    from db_manager import DBManager
except ImportError:
    from data_acquisition.db_manager import DBManager

try:
    from geo_config import DEFAULT_TARGET_CITY
except ImportError:
    from data_acquisition.geo_config import DEFAULT_TARGET_CITY

try:
    from tagging.remote_office_classifier import check_remote_office_status
    from tagging.location_enricher import LocationEnricher
except ImportError:
    from data_acquisition.tagging.remote_office_classifier import check_remote_office_status
    from data_acquisition.tagging.location_enricher import LocationEnricher


def _safe_float(val):
    """
    Sanitize floating point value: return float if valid finite number, else None.
    """
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def verify_location_tags(db_path=None, target_city=None, idempotent=True, enrich=False):
    """
    Verify and tag all records in the specified database.
    Optionally enriches coordinates via geocoding when enrich=True.
    Returns summary dictionary: {'total': int, 'updated': int, 'skipped': int, 'remote_count': int}
    """
    if db_path is None:
        db_path = os.environ.get("STARTUP_DB_PATH", "backend/startups.json")
    if target_city is None:
        target_city = DEFAULT_TARGET_CITY

    db = DBManager(db_path=db_path)
    enricher = LocationEnricher(db) if enrich else None
    
    # 1. Read the list of startups initially
    db.load_db()
    startups_to_process = list(db.startups)
    
    total_count = len(startups_to_process)
    updated_count = 0
    skipped_count = 0

    for temp_record in startups_to_process:
        if not isinstance(temp_record, dict):
            continue

        if idempotent and temp_record.get("location_tagged") is True:
            skipped_count += 1
            continue

        comp_id = temp_record.get("id")

        # 2. Geocode outside lock
        if enrich and enricher:
            rec_copy = dict(temp_record)
            if not idempotent:
                rec_copy["location_tagged"] = False
            enricher.enrich(rec_copy, target_city=target_city)
            new_lat = rec_copy.get("lat")
            new_lng = rec_copy.get("lng")
            new_city = rec_copy.get("city")
        else:
            new_lat = temp_record.get("lat")
            new_lng = temp_record.get("lng")
            new_city = temp_record.get("city")

        # 3. Enter lock, reload, apply updates, and save
        with DBManager.file_lock(db_path):
            db.load_db()
            record = next((x for x in db.startups if x.get("id") == comp_id), None)
            if not record:
                continue

            if idempotent and record.get("location_tagged") is True:
                skipped_count += 1
                continue

            # Apply coordinate updates
            record["lat"] = _safe_float(new_lat)
            record["lng"] = _safe_float(new_lng)
            if new_city:
                record["city"] = new_city

            # Run remote office classification
            check_remote_office_status(record, target_city=target_city)

            # Sanitize distance output
            if "remote_office_distance_km" in record:
                record["remote_office_distance_km"] = _safe_float(record.get("remote_office_distance_km"))

            record["location_tagged"] = True
            updated_count += 1
            db.save_db()

    # Get final remote count
    db.load_db()
    remote_count = sum(1 for s in db.startups if isinstance(s, dict) and s.get("is_remote_office") is True)

    return {
        "total": total_count,
        "updated": updated_count,
        "skipped": skipped_count,
        "remote_count": remote_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Batch Verify Location Tags and Classify Remote Offices")
    parser.add_argument("--db-path", default="backend/startups.json", help="Path to startup database JSON")
    parser.add_argument("--target-city", default=DEFAULT_TARGET_CITY, help="Target city for classification")
    parser.add_argument(
        "--idempotent",
        dest="idempotent",
        action="store_true",
        default=True,
        help="Skip records already marked location_tagged: True (default: True)"
    )
    parser.add_argument(
        "--force",
        "--no-idempotency",
        dest="idempotent",
        action="store_false",
        help="Force re-verification of all records ignoring location_tagged status"
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Run precision geocoding enrichment on records before classifying"
    )

    args = parser.parse_args()

    print(f"[Verify Location Tags] Using database: {args.db_path} (Target City: {args.target_city}, Idempotency: {args.idempotent}, Enrich: {args.enrich})")
    stats = verify_location_tags(db_path=args.db_path, target_city=args.target_city, idempotent=args.idempotent, enrich=args.enrich)

    print("-" * 50)
    print("Verification Summary:")
    print(f"  Total records    : {stats['total']}")
    print(f"  Updated records  : {stats['updated']}")
    print(f"  Skipped (tagged) : {stats['skipped']}")
    print(f"  Remote offices   : {stats['remote_count']}")
    print("-" * 50)

    sys.exit(0)


if __name__ == "__main__":
    main()
