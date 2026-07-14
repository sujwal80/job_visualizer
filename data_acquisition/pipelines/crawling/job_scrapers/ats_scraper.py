import os
import requests
import re
import time
import random
from data_acquisition.pipelines.crawling.job_scrapers.job_metadata_extractor import extract_job_metadata
from data_acquisition.geo_config import DEFAULT_TARGET_CITY, match_target_city
from data_acquisition.pipelines.crawling.job_scrapers.scraper_base import ScraperBase

class ATSScraper(ScraperBase):
    def __init__(self, validator=None):
        super().__init__(validator=validator)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }

    def _get_proxies(self):
        proxy = os.environ.get("PROXY_URL")
        return {"http": proxy, "https": proxy} if proxy else None

    def _slugify(self, name):
        if not name:
            return ""
        return re.sub(r'[^a-z0-9]+', '', str(name).lower())

    def get_jobs(self, company_name, start=0, target_city=None, **kwargs):
        if target_city is None:
            target_city = DEFAULT_TARGET_CITY
        if not company_name or str(company_name).strip() == "N/A":
            return []
        company_name = str(company_name).strip()
            
        slug = self._slugify(company_name)
        if not slug:
            return []
            
        jobs = []
        jobs.extend(self._fetch_lever(company_name, slug, target_city))
        if jobs:
            return self.validate_and_enrich_jobs(jobs)
            
        jobs.extend(self._fetch_greenhouse(company_name, slug, target_city))
        if jobs:
            return self.validate_and_enrich_jobs(jobs)
            
        jobs.extend(self._fetch_ashby(company_name, slug, target_city))
        return self.validate_and_enrich_jobs(jobs)

    def get_bangalore_jobs(self, company_name, start=0, target_city=None, **kwargs):
        return self.get_jobs(company_name, start=start, target_city=target_city, **kwargs)

    def _match_city(self, loc, target_city):
        return match_target_city(loc, target_city)

    def _get_with_retry(self, url, timeout=6):
        backoff = 1.0
        for attempt in range(3):
            try:
                self._sleep_throttle()
                res = requests.get(url, headers=self.headers, proxies=self._get_proxies(), timeout=timeout)
                if res.status_code == 429 or res.status_code >= 500:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                return res
            except Exception:
                time.sleep(backoff)
                backoff *= 2
        return None

    def _fetch_lever(self, company_name, slug, target_city):
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        try:
            res = self._get_with_retry(url)
            if res and res.status_code == 200:
                data = res.json()
                jobs = []
                for item in data:
                    loc = item.get("categories", {}).get("location", "")
                    if self._match_city(loc, target_city):
                        job_data = {
                            "title": item.get("text", "N/A"),
                            "company_name": company_name,
                            "job_url": item.get("hostedUrl", ""),
                            "location": loc or target_city,
                            "source": "Lever ATS"
                        }
                        snippet = item.get("descriptionPlain") or item.get("description") or ""
                        job_data.update(extract_job_metadata(item.get("text", "N/A"), raw_snippet=snippet, extra_data=item))
                        jobs.append(job_data)
                return jobs
        except Exception:
            pass
        return []

    def _fetch_greenhouse(self, company_name, slug, target_city):
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
        try:
            res = self._get_with_retry(url)
            if res and res.status_code == 200:
                data = res.json().get("jobs", [])
                jobs = []
                for item in data:
                    loc = item.get("location", {}).get("name", "")
                    if self._match_city(loc, target_city):
                        job_data = {
                            "title": item.get("title", "N/A"),
                            "company_name": company_name,
                            "job_url": item.get("absolute_url", ""),
                            "location": loc or target_city,
                            "source": "Greenhouse ATS"
                        }
                        snippet = item.get("content") or ""
                        job_data.update(extract_job_metadata(item.get("title", "N/A"), raw_snippet=snippet, extra_data=item))
                        jobs.append(job_data)
                return jobs
        except Exception:
            pass
        return []

    def _fetch_ashby(self, company_name, slug, target_city):
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        try:
            res = self._get_with_retry(url)
            if res and res.status_code == 200:
                data = res.json().get("jobs", [])
                jobs = []
                for item in data:
                    loc = item.get("location", "")
                    if self._match_city(loc, target_city):
                        job_data = {
                            "title": item.get("title", "N/A"),
                            "company_name": company_name,
                            "job_url": item.get("jobUrl", ""),
                            "location": loc or target_city,
                            "source": "Ashby ATS"
                        }
                        snippet = item.get("descriptionHtml") or item.get("descriptionPlain") or ""
                        job_data.update(extract_job_metadata(item.get("title", "N/A"), raw_snippet=snippet, extra_data=item))
                        jobs.append(job_data)
                return jobs
        except Exception:
            pass
        return []
