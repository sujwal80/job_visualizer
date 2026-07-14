#!/usr/bin/env python3
"""
Crawler Dispatcher and Delta Crawling Runner
Path: data_acquisition/pipelines/crawling/run_crawling.py
"""

import argparse
import os
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.db_manager import DBManager
from data_acquisition.pipelines.crawling.crawl_queue import CrawlQueue
from data_acquisition.geo_config import DEFAULT_TARGET_CITY

ALL_SOURCES = [
    "LinkedIn", "YC", "Indeed", "ATS", "Instahyre",
    "Wellfound", "Naukri", "Glassdoor", "Cutshort", "Hirist"
]

def main():
    parser = argparse.ArgumentParser(description="Run Crawler Dispatcher with Delta Crawling Check.")
    parser.add_argument("--db-path", default="backend/startups.json", help="Path to startup database JSON")
    parser.add_argument("--queue-db-path", default=None, help="Path to queue database file")
    parser.add_argument("--city", default="Bengaluru", help="Target city for filtering startups")
    parser.add_argument("--sources", default="all", help="Comma-separated sources or 'all'")
    parser.add_argument("--limit", type=int, default=None, help="Max startups to enqueue")
    parser.add_argument("--crawl-interval", type=int, default=86400, help="Crawl interval in seconds (default: 86400 / 1 day)")
    args = parser.parse_args()

    db_path = args.db_path
    if not os.path.isabs(db_path):
        db_path = os.path.join(PROJECT_ROOT, db_path)

    db_mgr = DBManager(db_path=db_path)
    db_mgr.load_db()

    current_time = time.time()
    matching_startups = []
    city_lower = str(args.city).strip().lower()

    for s in db_mgr.startups:
        s_city = str(s.get("city", "")).strip().lower()
        if city_lower == "india" or not city_lower or city_lower in s_city or s_city in city_lower:
            # Check delta crawling limit
            last_crawled = s.get("last_crawled")
            if last_crawled:
                try:
                    if isinstance(last_crawled, str):
                        last_crawled_time = datetime.fromisoformat(last_crawled).timestamp()
                    else:
                        last_crawled_time = float(last_crawled)
                    
                    if current_time - last_crawled_time < args.crawl_interval:
                        print(f"[Crawling] Skipping {s.get('name')} - age since last crawl ({current_time - last_crawled_time:.1f}s) is less than crawl interval ({args.crawl_interval}s).")
                        continue
                except Exception as e:
                    print(f"[Crawling] Error parsing last_crawled for {s.get('name')}: {e}")
            
            matching_startups.append(s)

    if args.limit and int(args.limit) > 0:
        matching_startups = matching_startups[:int(args.limit)]

    if not matching_startups:
        print("[Crawling] No startups need crawling at this time.")
        return

    if str(args.sources).strip().lower() == "all":
        target_sources = ALL_SOURCES
    else:
        target_sources = [x.strip() for x in str(args.sources).split(",") if x.strip()]

    q_path = args.queue_db_path
    if q_path and not os.path.isabs(q_path):
        q_path = os.path.join(PROJECT_ROOT, q_path)

    q = CrawlQueue(db_path=q_path)
    tasks = []
    
    with db_mgr.file_lock(db_mgr.db_path):
        db_mgr.load_db()
        for startup in matching_startups:
            comp_id = startup.get("id")
            comp_name = startup.get("name")
            
            # Find and update record in loaded db_mgr
            record = next((x for x in db_mgr.startups if x.get("id") == comp_id), None)
            if record:
                record["last_crawled"] = datetime.fromtimestamp(current_time).isoformat()
            
            for src in target_sources:
                tasks.append({
                    "source_name": src,
                    "company_id": comp_id,
                    "company_name": comp_name,
                    "target_city": args.city
                })

        db_mgr.save_db()

    queued_count = q.push_bulk(tasks)
    print(f"\n=======================================================")
    print(f" 🚀 CRAWLER DISPATCHED {queued_count} TASKS FOR '{args.city}' 🚀")
    print(f"=======================================================")
    print(f" Target Startups: {len(matching_startups)}")
    print(f" Scraper Sources: {', '.join(target_sources)}")
    print(f"=======================================================\n")

if __name__ == "__main__":
    main()
