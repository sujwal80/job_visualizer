#!/usr/bin/env python3
"""
Company Discovery Runner
Path: data_acquisition/pipelines/discovery/run_discovery.py
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.db_manager import DBManager
from data_acquisition.pipelines.discovery.discovery_service import CompanyDiscoveryService
from data_acquisition.pipelines.crawling.job_scrapers.linkedin_scraper import LinkedInScraper
from data_acquisition.pipelines.validation.job_validator import JobValidator
from data_acquisition.geo_config import DEFAULT_TARGET_CITY

def main():
    parser = argparse.ArgumentParser(description="Run Company Discovery Service.")
    parser.add_argument("--db-path", default="backend/startups.json", help="Path to startup database JSON")
    parser.add_argument("--target-city", default=DEFAULT_TARGET_CITY, help="Target city for discovery")
    parser.add_argument("--max-discovery", type=int, default=None, help="Maximum number of new companies to discover")
    parser.add_argument("--mock", action="store_true", help="Enable mock scraper mode")
    args = parser.parse_args()

    if args.mock:
        os.environ["MOCK_SCRAPER_FALLBACK"] = "true"

    db_path = args.db_path
    if not os.path.isabs(db_path):
        db_path = os.path.join(PROJECT_ROOT, db_path)

    db = DBManager(db_path=db_path)
    validator = JobValidator(db)
    linkedin_scraper = LinkedInScraper(validator=validator)
    discovery = CompanyDiscoveryService(db, linkedin_scraper, validator=validator)

    discovery.discover_new_companies(max_new_companies=args.max_discovery, target_city=args.target_city)

if __name__ == "__main__":
    main()
