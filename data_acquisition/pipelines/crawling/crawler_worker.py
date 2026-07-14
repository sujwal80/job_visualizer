#!/usr/bin/env python3
import argparse
import os
import sys
import time

try:
    from data_acquisition.crawl_queue import CrawlQueue
except ImportError:
    from crawl_queue import CrawlQueue

try:
    from data_acquisition.db_manager import DBManager
except ImportError:
    from db_manager import DBManager

try:
    import data_acquisition.job_scrapers as scrapers
except ImportError:
    import job_scrapers as scrapers


SCRAPER_MAP = {
    "LinkedIn": scrapers.LinkedInScraper,
    "YC": scrapers.YCScraper,
    "Indeed": scrapers.IndeedScraper,
    "ATS": scrapers.ATSScraper,
    "Instahyre": scrapers.InstahyreScraper,
    "Wellfound": scrapers.WellfoundScraper,
    "Naukri": scrapers.NaukriScraper,
    "Glassdoor": scrapers.GlassdoorScraper,
    "Cutshort": scrapers.CutshortScraper,
    "Hirist": scrapers.HiristScraper,
}


def run_worker(source_filter="all", exit_on_empty=False, max_tasks=None, db_path=None, json_path=None):
    queue = CrawlQueue(db_path=db_path)
    db_mgr = DBManager(db_path=json_path)

    print(f"[{os.getpid()}] 🚀 STARTING ASYNC CRAWLER WORKER (Queue: '{source_filter}') 🚀")
    tasks_processed = 0

    while True:
        if max_tasks is not None and tasks_processed >= int(max_tasks):
            print(f"[{os.getpid()}] Reached --max-tasks limit ({max_tasks}). Exiting cleanly.")
            break

        task = queue.pop_task(source_name=source_filter)
        if not task:
            if exit_on_empty:
                print(f"[{os.getpid()}] Queue '{source_filter}' is empty. --exit-on-empty set. Exiting cleanly.")
                break
            time.sleep(2.0)
            continue

        task_id = task["id"]
        source = task["source_name"]
        company = task["company_name"]
        city = task["target_city"]

        print(f"[{os.getpid()}] Processing Task #{task_id}: {source} -> '{company}' ({city})")

        scraper_cls = SCRAPER_MAP.get(source)
        if not scraper_cls:
            queue.fail_task(task_id, f"Unknown scraper source: {source}")
            continue

        try:
            scraper_inst = scraper_cls()
            jobs = scraper_inst.get_jobs(company, target_city=city)
            # Merge discovered jobs into database safely
            db_mgr.merge_job_openings(jobs)
            queue.complete_task(task_id, jobs_found=len(jobs))
            print(f"[{os.getpid()}] ✅ Completed Task #{task_id}: Found {len(jobs)} active jobs for '{company}'")
            tasks_processed += 1
        except Exception as e:
            err_msg = str(e)
            queue.fail_task(task_id, err_msg)
            print(f"[{os.getpid()}] ❌ Failed Task #{task_id} ({company}): {err_msg}")

    return tasks_processed


def main():
    parser = argparse.ArgumentParser(description="Consume crawler tasks from CrawlQueue.")
    parser.add_argument("--source", "--sources", dest="source", default="all", help="Source queue name (e.g. LinkedIn, YC, all)")
    parser.add_argument("--exit-on-empty", action="store_true", help="Exit immediately when queue is empty")
    parser.add_argument("--max-tasks", type=int, default=None, help="Maximum number of tasks to process before exiting")
    args = parser.parse_args()

    run_worker(source_filter=args.source, exit_on_empty=args.exit_on_empty, max_tasks=args.max_tasks)


if __name__ == "__main__":
    main()
