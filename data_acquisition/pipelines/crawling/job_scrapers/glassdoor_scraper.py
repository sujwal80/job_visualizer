import os
import requests
from bs4 import BeautifulSoup
import urllib.parse
import time
from data_acquisition.pipelines.crawling.job_scrapers.job_metadata_extractor import extract_job_metadata
from data_acquisition.geo_config import DEFAULT_TARGET_CITY, match_target_city
from data_acquisition.pipelines.crawling.job_scrapers.scraper_base import ScraperBase

class GlassdoorScraper(ScraperBase):
    """
    Scraper module to find job openings via Glassdoor.
    """
    def __init__(self, validator=None):
        super().__init__(validator=validator)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5"
        }

    def _get_proxies(self):
        proxy = os.environ.get("PROXY_URL")
        return {"http": proxy, "https": proxy} if proxy else None

    def _match_city(self, loc, target_city):
        return match_target_city(loc, target_city)

    def _get_with_retry(self, url, params=None, timeout=10):
        backoff = 1.0
        for attempt in range(3):
            try:
                self._sleep_throttle()
                res = requests.get(url, headers=self.headers, params=params, proxies=self._get_proxies(), timeout=timeout)
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
        if not keywords or keywords == "N/A":
            return []

        domain = os.environ.get("GLASSDOOR_DOMAIN", "www.glassdoor.co.in")
        url = f"https://{domain}/Job/jobs.htm"
        params = {
            "sc.keyword": keywords,
            "locT": "C",
            "locName": target_city
        }

        try:
            res = self._get_with_retry(url, params=params)
            if not res or res.status_code != 200:
                return []

            soup = BeautifulSoup(res.text, 'html.parser')
            job_listings = soup.find_all('li', class_=lambda x: x and ('react-job-listing' in x or 'JobsList_jobListItem' in x or 'job-listing' in x))
            jobs = []

            for item in job_listings:
                title_el = item.find('a', class_=lambda x: x and ('job-title' in x or 'JobCard_jobTitle' in x or 'jobLink' in x)) or item.find('a', {'data-test': 'job-link'})
                comp_el = item.find('span', class_=lambda x: x and ('EmployerProfile_compactEmployerName' in x or 'employer-name' in x)) or item.find('div', {'data-test': 'employer-name'})
                loc_el = item.find('span', class_=lambda x: x and ('location' in x or 'JobCard_location' in x)) or item.find('div', {'data-test': 'emp-location'})

                if not title_el:
                    continue

                raw_title = title_el.text.strip()
                comp_name = comp_el.text.strip() if comp_el else keywords
                location = loc_el.text.strip() if loc_el else target_city

                if not self._match_city(location, target_city):
                    continue

                href = title_el.get('href', '')
                if href.startswith('/'):
                    job_url = f"https://{domain}{href}"
                elif href:
                    job_url = href
                else:
                    job_url = f"https://{domain}/Job/jobs.htm?sc.keyword={urllib.parse.quote(keywords)}"

                job_data = {
                    "title": str(raw_title).strip(),
                    "company_name": str(comp_name).strip(),
                    "job_url": str(job_url).strip(),
                    "location": str(location).strip(),
                    "source": "Glassdoor"
                }
                snippet_text = item.text.strip() if item else ""
                job_data.update(extract_job_metadata(str(raw_title).strip(), raw_snippet=snippet_text))
                jobs.append(job_data)

            return self.validate_and_enrich_jobs(jobs)
        except Exception as e:
            print(f"[Glassdoor Scraper] Error fetching jobs: {str(e)}")
            return []

    def get_bangalore_jobs(self, keywords, start=0, target_city=None, **kwargs):
        return self.get_jobs(keywords, start=start, target_city=target_city, **kwargs)
