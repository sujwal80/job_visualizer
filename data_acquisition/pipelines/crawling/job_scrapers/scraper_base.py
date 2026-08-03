import os
import random
import time
from data_acquisition.pipelines.crawling.job_scrapers.job_metadata_extractor import extract_job_metadata
from data_acquisition.pipelines.validation.job_validator import JobValidator


def resolve_job_source(job, default_source=None):
    if not isinstance(job, dict):
        return default_source or "Direct"
    src = str(job.get("source") or "").strip()
    url = str(job.get("url") or job.get("job_url") or "").strip().lower()

    if "linkedin.com" in url or "licdn.com" in url:
        return "LinkedIn"
    if "instahyre.com" in url:
        return "Instahyre"
    if "ycombinator.com" in url or "workatastartup.com" in url:
        return "Y Combinator"
    if "greenhouse.io" in url:
        return "Greenhouse ATS"
    if "lever.co" in url:
        return "Lever ATS"
    if "ashbyhq.com" in url:
        return "Ashby ATS"
    if "indeed.com" in url:
        return "Indeed"
    if "wellfound.com" in url or "angel.co" in url:
        return "Wellfound"
    if "naukri.com" in url:
        return "Naukri"
    if "glassdoor." in url:
        return "Glassdoor"
    if "cutshort." in url:
        return "Cutshort"
    if "hirist." in url:
        return "Hirist"

    src_lower = src.lower()
    if "linkedin" in src_lower:
        return "LinkedIn"
    if "instahyre" in src_lower:
        return "Instahyre"
    if "ycombinator" in src_lower or src_lower == "yc":
        return "Y Combinator"
    if "greenhouse" in src_lower:
        return "Greenhouse ATS"
    if "lever" in src_lower:
        return "Lever ATS"
    if "ashby" in src_lower:
        return "Ashby ATS"
    if "indeed" in src_lower:
        return "Indeed"
    if "wellfound" in src_lower or "angellist" in src_lower:
        return "Wellfound"
    if "naukri" in src_lower:
        return "Naukri"
    if "glassdoor" in src_lower:
        return "Glassdoor"
    if "cutshort" in src_lower:
        return "Cutshort"
    if "hirist" in src_lower:
        return "Hirist"

    if src and "company" not in src_lower and src_lower != "direct":
        return src
    return default_source or "Direct"


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
        cls_name = self.__class__.__name__.lower()
        default_src = "LinkedIn" if "linkedin" in cls_name else None
        for job in raw_jobs:
            if not isinstance(job, dict):
                continue
            url = str(job.get("url") or job.get("job_url") or "").strip()
            title = str(job.get("title") or "Unknown Role").strip()
            job["url"] = url
            job["job_url"] = url
            job["source"] = resolve_job_source(job, default_source=default_src)

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

