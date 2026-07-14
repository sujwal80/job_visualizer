import os
import requests
import re
import time
import random
import urllib.parse
import concurrent.futures

try:
    from geo_config import TEST_FIXTURE_WHITELIST_URLS
except ImportError:
    from data_acquisition.geo_config import TEST_FIXTURE_WHITELIST_URLS

try:
    from utils.validation import validate_website_domain, check_job_active, validate_logo_image
except ImportError:
    from data_acquisition.utils.validation import validate_website_domain, check_job_active, validate_logo_image

EXPIRED_KEYWORDS = [
    "no longer accepting applications",
    "job is closed",
    "position has been filled",
    "job expired",
    "posting is no longer available",
    "this job is no longer active",
    "job not found",
    "page not found",
    "position is closed",
    "position closed",
    "no longer hiring",
    "applications closed",
    "job closed",
    "this role is closed"
]

class JobValidator:
    """
    Data validation and removal module.
    Pings active job URLs in the database to verify if they are still open.
    Prunes expired links, closed applications, or broken URLs.
    """
    def __init__(self, db_manager, concurrency=1):
        self.db = db_manager
        self.concurrency = concurrency
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

    def _validate_job_worker(self, job):
        if not isinstance(job, dict):
            return None, "Invalid job record", "Unknown Role"
        url = str(job.get("url") or job.get("job_url") or "").strip()
        title = str(job.get("title") or "Unknown Role").strip()
        job["url"] = url
        job["job_url"] = url

        if not url or url == "N/A" or not url.startswith(("http://", "https://")):
            return None, "Invalid/missing URL", title

        is_active, reason = check_job_active(url)
        if is_active:
            return job, "Active", title
        else:
            return None, reason, title

    def _validate_flat_job_worker(self, task):
        startup, job = task
        res_job, reason, title = self._validate_job_worker(job)
        return startup, res_job, reason, title

    def validate_and_prune(self, max_startups=None):
        print("\n==========================================================")
        print("=== STARTING LIVE PROD VALIDATION & EXPIRED JOB REMOVAL ===")
        print("==========================================================")
        
        processed_startups = []
        processed = 0
        for startup in self.db.startups:
            processed += 1
            if max_startups and processed > max_startups:
                print(f"[Job Validator] Reached max_startups limit ({max_startups}). Stopping collection.")
                break
            processed_startups.append(startup)
            
        job_tasks = []
        startups_to_validate_website = []
        for startup in processed_startups:
            startups_to_validate_website.append(startup)
            jobs = startup.get("job_openings", [])
            for job in jobs:
                job_tasks.append((startup, job))


        total_pruned = 0
        if job_tasks:
            if self.concurrency > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                    results = list(executor.map(self._validate_flat_job_worker, job_tasks))
            else:
                results = [self._validate_flat_job_worker(task) for task in job_tasks]
                
            valid_jobs_map = {id(startup): [] for startup in startups_to_validate_website}
            for startup, res_job, reason, title in results:
                if res_job is not None:
                    valid_jobs_map[id(startup)].append(res_job)
                else:
                    total_pruned += 1

            for startup in startups_to_validate_website:
                old_count = len(startup.get("job_openings", []))
                valid_jobs = valid_jobs_map[id(startup)]
                pruned_for_company = old_count - len(valid_jobs)
                if pruned_for_company > 0:
                    comp_name = startup.get("name", "N/A")
                    print(f"  [~] Company '{comp_name}': Pruned {pruned_for_company} non-valid/expired jobs (Remaining active: {len(valid_jobs)})")
                    startup["job_openings"] = valid_jobs

        if startups_to_validate_website:
            if self.concurrency > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                    list(executor.map(self.validate_company_status, startups_to_validate_website))
            else:
                for startup in startups_to_validate_website:
                    self.validate_company_status(startup)

        self.db.save_db()
                
        print("\n=== LIVE PROD DATA VALIDATION FINISHED ===")
        print(f"Total expired/invalid jobs pruned from database: {total_pruned}")
        return total_pruned

    def validate_company_status(self, startup):
        hr = startup.get("hr_details", {}) if isinstance(startup.get("hr_details"), dict) else {}
        email = hr.get("contact_email", "")
        if email and re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
            startup["verified_email"] = email
        else:
            startup["verified_email"] = ""

        web = startup.get("website", "")
        if web and web != "N/A" and web.startswith(("http://", "https://")):
            is_active, healed_url, reason = validate_website_domain(web, headers=self.headers)
            startup["is_active_website"] = is_active
            startup["website"] = healed_url
        else:
            startup["is_active_website"] = True

        # Metadata Auto-cleaning
        if not startup.get("is_active_website", True):
            startup["logo_svg_url"] = ""
            startup["verified_email"] = ""
        else:
            logo_svg_url = startup.get("logo_svg_url")
            if logo_svg_url:
                if not validate_logo_image(logo_svg_url):
                    startup["logo_svg_url"] = ""

    def _check_job_active(self, url):
        is_active, reason = check_job_active(url)
        return is_active, reason

