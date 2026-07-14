import os
import random
import time
from data_acquisition.pipelines.crawling.job_scrapers.job_metadata_extractor import extract_job_metadata
from data_acquisition.pipelines.validation.job_validator import JobValidator


class ScraperBase:
    """
    Base class for all job scrapers providing integrated metadata extraction
    and active job link validation before returning/submitting scraped jobs.
    """
    def __init__(self, validator=None):
        self.validator = validator or JobValidator(None)

    def validate_and_enrich_jobs(self, raw_jobs):
        if not isinstance(raw_jobs, list):
            return []
        valid_jobs = []
        for job in raw_jobs:
            if not isinstance(job, dict):
                continue
            url = str(job.get("url") or job.get("job_url") or "").strip()
            title = str(job.get("title") or "Unknown Role").strip()
            job["url"] = url
            job["job_url"] = url

            # Extract and update metadata
            snippet = str(job.get("description") or job.get("snippet") or "")
            extracted = extract_job_metadata(title, raw_snippet=snippet, extra_data=job)
            for k, v in extracted.items():
                if k not in job or job[k] in (None, "", "Not specified", "Not disclosed"):
                    job[k] = v

            # Validate that the job posting/link is active
            if not url or url == "N/A":
                continue

            is_active, reason = self.validator._check_job_active(url)
            if is_active:
                valid_jobs.append(job)
            else:
                print(f"[{self.__class__.__name__}] Filtered inactive job '{title}' -> {reason}")

        return valid_jobs

    def _sleep_throttle(self, min_s=1.0, max_s=2.0):
        mult = float(os.environ.get("DELAY_MULTIPLIER", 0.0))
        if mult > 0:
            time.sleep(random.uniform(min_s, max_s) * mult)

