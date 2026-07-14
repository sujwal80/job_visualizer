#!/usr/bin/env python3
import argparse
import os
import sys

from data_acquisition.pipelines.crawling.crawl_queue import CrawlQueue
from data_acquisition.db_manager import DBManager


ALL_SOURCES = [
    "LinkedIn", "YC", "Indeed", "ATS", "Instahyre",
    "Wellfound", "Naukri", "Glassdoor", "Cutshort", "Hirist"
]


def dispatch(city="Bengaluru", sources="all", limit=None, db_path=None, json_path=None):
    db_mgr = DBManager(db_path=json_path)
    startups = db_mgr.get_all_startups()

    matching_startups = []
    city_lower = str(city).strip().lower()
    for s in startups:
        s_city = str(s.get("city", "")).strip().lower()
        if city_lower == "india" or not city_lower or city_lower in s_city or s_city in city_lower:
            matching_startups.append(s)

    if limit and int(limit) > 0:
        matching_startups = matching_startups[:int(limit)]

    if str(sources).strip().lower() == "all":
        target_sources = ALL_SOURCES
    else:
        target_sources = [x.strip() for x in str(sources).split(",") if x.strip()]

    q = CrawlQueue(db_path=db_path)
    tasks = []
    for startup in matching_startups:
        comp_id = startup.get("id")
        comp_name = startup.get("name")
        for src in target_sources:
            tasks.append({
                "source_name": src,
                "company_id": comp_id,
                "company_name": comp_name,
                "target_city": city
            })

    queued_count = q.push_bulk(tasks)
    print(f"\n=======================================================")
    print(f" 🚀 DISPATCHER ENQUEUED {queued_count} TASKS FOR '{city}' 🚀")
    print(f"=======================================================")
    print(f" Target Startups: {len(matching_startups)}")
    print(f" Scraper Sources: {', '.join(target_sources)}")
    print(f"=======================================================\n")

    print_queue_summary(q)
    return queued_count


def print_queue_summary(queue_instance):
    stats = queue_instance.get_queue_stats()
    print("-------------------------------------------------------------------------")
    print(f" {'SOURCE NAME':<16} | {'PENDING':<10} | {'PROCESSING':<12} | {'COMPLETED':<10} | {'FAILED':<8}")
    print("-------------------------------------------------------------------------")
    for src in sorted(stats.keys()):
        s = stats[src]
        print(f" {src:<16} | {s.get('PENDING',0):<10} | {s.get('PROCESSING',0):<12} | {s.get('COMPLETED',0):<10} | {s.get('FAILED',0):<8}")
    print("-------------------------------------------------------------------------\n")


def main():
    parser = argparse.ArgumentParser(description="Dispatch crawler tasks into CrawlQueue.")
    parser.add_argument("--city", default="Bengaluru", help="Target city or location (default: Bengaluru)")
    parser.add_argument("--sources", default="all", help="Comma-separated list of sources or 'all'")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of startups to enqueue")
    args = parser.parse_args()
    dispatch(city=args.city, sources=args.sources, limit=args.limit)


if __name__ == "__main__":
    main()
