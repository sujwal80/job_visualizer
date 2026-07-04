import os
import requests
from bs4 import BeautifulSoup
import urllib.parse
import time
import random
import re
try:
    from job_metadata_extractor import extract_job_metadata
except ImportError:
    from data_acquisition.job_metadata_extractor import extract_job_metadata

class GlassdoorScraper:
    """
    Scraper module to find job openings via Glassdoor.
    """
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5"
        }

    def _get_proxies(self):
        proxy = os.environ.get("PROXY_URL")
        return {"http": proxy, "https": proxy} if proxy else None

    def _sleep_throttle(self, min_s=1.0, max_s=2.0):
        mult = float(os.environ.get("DELAY_MULTIPLIER", 1.0))
        time.sleep(random.uniform(min_s, max_s) * mult)

    def _match_city(self, loc, target_city):
        if not loc:
            return False
        loc_lower = str(loc).lower()
        target_lower = target_city.lower()
        if target_lower in loc_lower:
            return True
        if target_lower == "bengaluru" and "bangalore" in loc_lower:
            return True
        if target_lower == "bangalore" and "bengaluru" in loc_lower:
            return True
        return False

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

    def get_bangalore_jobs(self, keywords, start=0, target_city="Bengaluru", **kwargs):
        if not keywords or keywords == "N/A":
            return []

        url = "https://www.glassdoor.co.in/Job/jobs.htm"
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
                    job_url = f"https://www.glassdoor.co.in{href}"
                elif href:
                    job_url = href
                else:
                    job_url = f"https://www.glassdoor.co.in/Job/jobs.htm?sc.keyword={urllib.parse.quote(keywords)}"

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

            return jobs
        except Exception as e:
            print(f"[Glassdoor Scraper] Error fetching jobs: {str(e)}")
            return []
