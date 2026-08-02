#!/usr/bin/env python3
"""
Automated Hourly Re-Validation Service & Live Dataset Synchronizer
Path: data_acquisition/revalidate_hourly_service.py

Supports:
- --run-once (for @hourly / 0 * * * * cron or CI execution)
- --daemon (continuous loop running every 3600 seconds with structured logging)
- --db and --public-db custom paths
- Atomic database locking and synchronization between backend and public datasets.
"""

import argparse
import json
import logging
import os
import shutil
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.db_manager import DBManager
from data_acquisition.revalidate_healing_engine import RevalidationHealingEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("RevalidateHourlyService")


def run_service_once(db_path="backend/startups.json", public_db_path="public/static/data/startups.json") -> dict:
    """
    Execute a single atomic re-validation, healing, and synchronization pass across
    backend/startups.json and public/static/data/startups.json.
    Returns metrics dict.
    """
    abs_db = os.path.abspath(db_path)
    abs_public_db = os.path.abspath(public_db_path)

    logger.info(f"Starting atomic re-validation & healing on {abs_db}...")

    with DBManager.file_lock(abs_db):
        engine = RevalidationHealingEngine(db_path=abs_db)
        metrics = engine.revalidate_and_heal_all(dry_run=False)

        # Atomically synchronize backend DB to public static DB
        os.makedirs(os.path.dirname(abs_public_db), exist_ok=True)
        tmp_public = abs_public_db + ".tmp_sync"
        shutil.copy2(abs_db, tmp_public)
        os.replace(tmp_public, abs_public_db)

    logger.info(
        "Atomic re-validation and synchronization completed successfully:\n"
        f"  Foreign TLDs Healed  : {metrics['foreign_tlds_healed']}\n"
        f"  Duplicates Merged    : {metrics['duplicates_merged']}\n"
        f"  Addresses Preserved  : {metrics['addresses_preserved']}\n"
        f"  Out of Bounds Fixed  : {metrics['out_of_bounds_fixed']}\n"
        f"  Total Active Records : {metrics['total_records']}\n"
        f"  Synchronized File    : {abs_public_db}"
    )

    return metrics


def run_daemon_loop(db_path="backend/startups.json", public_db_path="public/static/data/startups.json", interval_seconds=3600):
    """
    Run continuous loop executing run_service_once every interval_seconds (default 3600).
    """
    logger.info(f"Starting re-validation daemon mode (interval={interval_seconds}s)...")
    try:
        while True:
            try:
                run_service_once(db_path=db_path, public_db_path=public_db_path)
            except Exception as e:
                logger.error(f"Error during scheduled re-validation pass: {e}", exc_info=True)

            logger.info(f"Sleeping for {interval_seconds} seconds before next hourly cycle...")
            time.sleep(interval_seconds)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Daemon service stopped gracefully.")


def main():
    parser = argparse.ArgumentParser(description="Automated Hourly Re-Validation Service")
    parser.add_argument("--run-once", action="store_true", help="Execute single re-validation pass and exit")
    parser.add_argument("--daemon", action="store_true", help="Run continuously every 3600 seconds")
    parser.add_argument("--db", default="backend/startups.json", help="Path to startups database JSON")
    parser.add_argument("--public-db", default="public/static/data/startups.json", help="Path to public startups JSON")
    parser.add_argument("--interval", type=int, default=3600, help="Interval in seconds for daemon mode")
    args = parser.parse_args()

    if args.daemon:
        run_daemon_loop(db_path=args.db, public_db_path=args.public_db, interval_seconds=args.interval)
    else:
        # Default to run_once behavior if neither or --run-once is specified
        metrics = run_service_once(db_path=args.db, public_db_path=args.public_db)
        print(f"=== SERVICE RUN-ONCE COMPLETE ===")
        print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
