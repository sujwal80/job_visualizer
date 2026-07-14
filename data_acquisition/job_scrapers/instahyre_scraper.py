import os
import requests
import time
import random
import re
import urllib.parse
try:
    from job_metadata_extractor import extract_job_metadata
except ImportError:
    from data_acquisition.job_metadata_extractor import extract_job_metadata

try:
    from geo_config import DEFAULT_TARGET_CITY, match_target_city, get_mock_jobs
except ImportError:
    from data_acquisition.geo_config import DEFAULT_TARGET_CITY, match_target_city, get_mock_jobs

try:
    from scraper_base import ScraperBase
except ImportError:
    from data_acquisition.job_scrapers.scraper_base import ScraperBase

class InstahyreScraper(ScraperBase):
    def __init__(self, validator=None):
        super().__init__(validator=validator)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9"
        }
        self.known_employers = {}

    def _get_proxies(self):
        proxy = os.environ.get("PROXY_URL")
        return {"http": proxy, "https": proxy} if proxy else None

    def _slugify(self, name):
        if not name:
            return "unknown-company"
        return re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-')

    def _get_with_retry(self, url, params):
        backoff = 1.0
        for attempt in range(3):
            try:
                self._sleep_throttle()
                res = requests.get(url, headers=self.headers, params=params, proxies=self._get_proxies(), timeout=10)
                if res.status_code == 429 or res.status_code >= 500:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                return res
            except Exception:
                time.sleep(backoff)
                backoff *= 2
        return None

    def get_jobs(self, keywords, start=0, target_city=None, **kwargs):
        if target_city is None:
            target_city = DEFAULT_TARGET_CITY
        """
        Fetch jobs from Instahyre's public REST search API.
        Returns a list of dicts: {title, company_name, company_slug, job_url, location, source}
        """
        if not keywords or str(keywords).strip() == "N/A":
            return []
        keywords = str(keywords).strip()
        target_city = str(target_city or DEFAULT_TARGET_CITY).strip()
        url = "https://www.instahyre.com/api/v1/job_search"
        api_loc = "Bangalore" if target_city.lower() in ["bengaluru", "bangalore"] else target_city
        params = {
            "location": api_loc,
            "search": keywords,
            "offset": start
        }

        try:
            response = self._get_with_retry(url, params)
            if not response or response.status_code != 200:
                status = response.status_code if response else "None"
                print(f"[Instahyre Scraper] Jobs fetch failed with status code {status}")
                return []

            data = response.json()
            objects = data.get("objects", [])
            jobs = []

            for obj in objects:
                if not isinstance(obj, dict):
                    continue

                title = obj.get("candidate_title") or obj.get("title") or "N/A"
                job_url = obj.get("public_url") or ""
                location = obj.get("locations") or target_city

                # Strict city location filtering per grill-me decision
                city_match = match_target_city(location, target_city)
                if not city_match:
                    continue

                employer = obj.get("employer", {})
                if not isinstance(employer, dict):
                    employer = {}

                comp_name = employer.get("company_name") or "N/A"
                comp_slug = self._slugify(comp_name)

                # Cache employer metadata for get_company_details
                if comp_slug not in self.known_employers:
                    desc = employer.get("instahyre_note") or employer.get("company_tagline") or ""
                    self.known_employers[comp_slug] = {
                        "name": comp_name,
                        "website": "",
                        "industry": "Software",
                        "head_count": employer.get("employee_count") or 10,
                        "headquarters": target_city,
                        "description": desc.strip(),
                        "bangalore_address": target_city,
                        "office_address": target_city,
                        "logo_domain": ""
                    }

                snippet_text = employer.get("instahyre_note") or employer.get("company_tagline") or ""
                job_data = {
                    "title": str(title).strip(),
                    "company_name": str(comp_name).strip(),
                    "company_slug": comp_slug,
                    "job_url": str(job_url).strip(),
                    "location": str(location).strip(),
                    "source": "Instahyre"
                }
                job_data.update(extract_job_metadata(str(title).strip(), raw_snippet=str(snippet_text), extra_data=obj))
                jobs.append(job_data)

            if not jobs and os.environ.get("MOCK_SCRAPER_FALLBACK", "false").lower() == "true":
                return self.validate_and_enrich_jobs(get_mock_jobs("Instahyre", keywords, target_city))
            return self.validate_and_enrich_jobs(jobs)

        except Exception as e:
            print(f"[Instahyre Scraper] Error fetching jobs: {str(e)}")
            if os.environ.get("MOCK_SCRAPER_FALLBACK", "false").lower() == "true":
                return self.validate_and_enrich_jobs(get_mock_jobs("Instahyre", keywords, target_city))
            return []

    def get_bangalore_jobs(self, keywords, start=0, target_city=None, **kwargs):
        return self.get_jobs(keywords, start=start, target_city=target_city, **kwargs)

    def get_company_details(self, company_slug):
        """
        Return cached employer metadata retrieved during job search.
        """
        return self.known_employers.get(company_slug)
