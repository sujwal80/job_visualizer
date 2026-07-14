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
        
        self.db.load_db()
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
                job_tasks.append((startup, dict(job)))

        total_pruned = 0
        valid_jobs_map = {startup.get("id"): [] for startup in startups_to_validate_website}
        
        if job_tasks:
            def run_task(task):
                st, j = task
                res_job, reason, title = self._validate_job_worker(j)
                return st.get("id"), res_job, reason, title

            if self.concurrency > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                    results = list(executor.map(run_task, job_tasks))
            else:
                results = [run_task(task) for task in job_tasks]
                
            for s_id, res_job, reason, title in results:
                if res_job is not None:
                    valid_jobs_map[s_id].append(res_job)
                else:
                    total_pruned += 1

        company_status_updates = {}
        for startup in startups_to_validate_website:
            s_id = startup.get("id")
            comp_copy = dict(startup)
            self.validate_company_status(comp_copy)
            company_status_updates[s_id] = {
                "verified_email": comp_copy.get("verified_email", ""),
                "is_active_website": comp_copy.get("is_active_website", True),
                "website": comp_copy.get("website", ""),
                "logo_svg_url": comp_copy.get("logo_svg_url", "")
            }

        with self.db.file_lock(self.db.db_path):
            self.db.load_db()
            for startup in self.db.startups:
                s_id = startup.get("id")
                if s_id not in [s.get("id") for s in startups_to_validate_website]:
                    continue
                
                validated_any = any(st.get("id") == s_id for st, _ in job_tasks)
                if validated_any:
                    old_jobs = startup.get("job_openings", [])
                    old_count = len(old_jobs)
                    
                    checked_urls = {job_url for s_id_task, job_url in [
                        (st.get("id"), j.get("url") or j.get("job_url")) for st, j in job_tasks
                    ] if s_id_task == s_id}
                    
                    concurrent_jobs = [j for j in old_jobs if (j.get("url") or j.get("job_url")) not in checked_urls]
                    
                    startup["job_openings"] = valid_jobs_map.get(s_id, []) + concurrent_jobs
                    pruned_for_company = old_count - len(startup["job_openings"])
                    if pruned_for_company > 0:
                        comp_name = startup.get("name", "N/A")
                        print(f"  [~] Company '{comp_name}': Pruned {pruned_for_company} non-valid/expired jobs (Remaining active: {len(startup['job_openings'])})")
                
                if s_id in company_status_updates:
                    updates = company_status_updates[s_id]
                    startup["verified_email"] = updates["verified_email"]
                    startup["is_active_website"] = updates["is_active_website"]
                    startup["website"] = updates["website"]
                    startup["logo_svg_url"] = updates["logo_svg_url"]
                    
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

