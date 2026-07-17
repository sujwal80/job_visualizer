#!/usr/bin/env python3
"""
Pipeline & CrawlQueue Real-Time Monitor
Displays current queue metrics, crawler completion rates, and startup database health statistics.
"""

import os
import sys
import json

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from data_acquisition.pipelines.crawling.crawl_queue import CrawlQueue


def display_monitor(db_path=None, queue_db_path=None):
    if db_path is None:
        db_path = os.environ.get("STARTUP_DB_PATH", os.path.join(PROJECT_ROOT, "backend", "startups.json"))

    print("=========================================================================")
    print("                STARTUP PIPELINE & CRAWLER MONITOR                       ")
    print("=========================================================================")

    # 1. Inspect CrawlQueue
    try:
        q = CrawlQueue(db_path=queue_db_path)
        stats = q.get_queue_stats()
        print("\n [CRAWL QUEUE STATUS]")
        print(" -----------------------------------------------------------------------")
        print(f" {'SOURCE NAME':<16} | {'PENDING':<10} | {'PROCESSING':<12} | {'COMPLETED':<10} | {'FAILED':<8}")
        print(" -----------------------------------------------------------------------")
        total_p = total_r = total_c = total_f = 0
        for src in sorted(stats.keys()):
            s = stats[src]
            p = s.get('PENDING', 0)
            r = s.get('PROCESSING', 0)
            c = s.get('COMPLETED', 0)
            f = s.get('FAILED', 0)
            total_p += p
            total_r += r
            total_c += c
            total_f += f
            print(f" {src:<16} | {p:<10} | {r:<12} | {c:<10} | {f:<8}")
        print(" -----------------------------------------------------------------------")
        print(f" {'TOTAL':<16} | {total_p:<10} | {total_r:<12} | {total_c:<10} | {total_f:<8}")
        print(" -----------------------------------------------------------------------")
    except Exception as e:
        print(f"  [Error reading queue]: {e}")

    # 2. Inspect Database Metrics
    try:
        if os.path.exists(db_path):
            with open(db_path, "r", encoding="utf-8") as f:
                startups = json.load(f)
            total_startups = len(startups)
            total_jobs = sum(len(s.get("job_openings", [])) for s in startups if isinstance(s, dict))
            hiring_companies = sum(1 for s in startups if isinstance(s, dict) and len(s.get("job_openings", [])) > 0)
            remote_count = sum(1 for s in startups if isinstance(s, dict) and s.get("is_remote_office") is True)
            tagged_count = sum(1 for s in startups if isinstance(s, dict) and s.get("location_tagged") is True)

            print("\n [DATABASE HEALTH METRICS]")
            print(" -----------------------------------------------------------------------")
            print(f"  Database Path          : {db_path}")
            print(f"  Total Startups         : {total_startups}")
            print(f"  Startups Hiring        : {hiring_companies}")
            print(f"  Total Active Job Openings : {total_jobs}")
            print(f"  Remote Offices Tagged  : {remote_count}")
            print(f"  Locations Verified     : {tagged_count} / {total_startups}")
            print(" -----------------------------------------------------------------------")
        else:
            print(f"  [Database file not found at]: {db_path}")
    except Exception as e:
        print(f"  [Error reading database]: {e}")

    print("=========================================================================\n")


if __name__ == "__main__":
    display_monitor()
