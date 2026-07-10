#!/usr/bin/env python3
"""
Job Link Validation and Pruning Runner
Validates all job links across the startup database, checks active status,
and removes invalid, expired, or closed job postings.
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
DATA_ACQ_DIR = os.path.abspath(os.path.dirname(__file__))
if DATA_ACQ_DIR not in sys.path:
    sys.path.insert(0, DATA_ACQ_DIR)

try:
    from db_manager import DBManager
except ImportError:
    from data_acquisition.db_manager import DBManager

try:
    from job_validator import JobValidator
except ImportError:
    from data_acquisition.job_validator import JobValidator


def main():
    parser = argparse.ArgumentParser(description="Run JobValidator to verify and prune invalid/expired job links.")
    parser.add_argument("--db-path", default="backend/startups.json", help="Path to startup database JSON")
    parser.add_argument("--max-startups", type=int, default=None, help="Maximum number of startups to validate")
    parser.add_argument("--mock", action="store_true", help="Enable mock/fast validation mode")
    args = parser.parse_args()

    if args.mock:
        os.environ["MOCK_SCRAPER_FALLBACK"] = "true"

    db_path = args.db_path
    if not os.path.isabs(db_path):
        db_path = os.path.join(PROJECT_ROOT, db_path)

    print(f"[Run Validator] Loading database from: {db_path}")
    db = DBManager(db_path=db_path)
    validator = JobValidator(db)

    total_before_jobs = sum(len(s.get("job_openings", [])) for s in db.startups if isinstance(s, dict))
    print(f"[Run Validator] Total Startups: {len(db.startups)} | Total Job Openings Before: {total_before_jobs}")

    pruned_count = validator.validate_and_prune(max_startups=args.max_startups)

    total_after_jobs = sum(len(s.get("job_openings", [])) for s in db.startups if isinstance(s, dict))
    print("\n==========================================================")
    print("=== VALIDATION & PRUNING RUN SUMMARY ===")
    print("==========================================================")
    print(f"  Total Startups Audited      : {len(db.startups)}")
    print(f"  Job Openings Before         : {total_before_jobs}")
    print(f"  Non-Valid/Expired Pruned    : {pruned_count}")
    print(f"  Valid Active Jobs Remaining : {total_after_jobs}")
    print("==========================================================\n")


if __name__ == "__main__":
    main()
