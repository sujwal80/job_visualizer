import os
import requests
from bs4 import BeautifulSoup
import urllib.parse
import time
import random
import re
from data_acquisition.pipelines.crawling.job_scrapers.job_metadata_extractor import extract_job_metadata
from data_acquisition.geo_config import DEFAULT_TARGET_CITY, match_target_city
from data_acquisition.pipelines.crawling.job_scrapers.scraper_base import ScraperBase

class IndeedScraper(ScraperBase):
    """
    Scraper module to find job openings via Indeed.
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

        domain = os.environ.get("INDEED_DOMAIN", "in.indeed.com")
        url = f"https://{domain}/jobs"
        params = {
            "q": keywords,
            "l": target_city,
            "start": start
        }

        try:
            res = self._get_with_retry(url, params=params)
            if not res or res.status_code != 200:
                return []

            soup = BeautifulSoup(res.text, 'html.parser')
            job_cards = soup.find_all('div', class_=lambda x: x and ('job_seen_beacon' in x or 'cardOutline' in x))
            jobs = []

            for card in job_cards:
                title_el = card.find('h2', class_=lambda x: x and 'jobTitle' in x) or card.find('a', class_=lambda x: x and 'jcs-JobTitle' in x)
                company_el = card.find('span', class_=lambda x: x and 'companyName' in x) or card.find('span', {'data-testid': 'company-name'})
                loc_el = card.find('div', class_=lambda x: x and 'companyLocation' in x) or card.find('div', {'data-testid': 'text-location'})

                if not title_el:
                    continue

                raw_title = title_el.text.strip()
                comp_name = company_el.text.strip() if company_el else keywords
                location = loc_el.text.strip() if loc_el else target_city

                if not self._match_city(location, target_city):
                    continue

                link_el = card.find('a', href=True)
                job_url = ""
                if link_el:
                    href = link_el['href']
                    if href.startswith('/'):
                        job_url = f"https://{domain}{href}"
                    else:
                        job_url = href
                else:
                    job_url = f"https://{domain}/jobs?q={urllib.parse.quote(keywords)}"

                job_data = {
                    "title": str(raw_title).strip(),
                    "company_name": str(comp_name).strip(),
                    "job_url": str(job_url).strip(),
                    "location": str(location).strip(),
                    "source": "Indeed"
                }
                snippet_text = card.text.strip() if card else ""
                job_data.update(extract_job_metadata(str(raw_title).strip(), raw_snippet=snippet_text))
                jobs.append(job_data)

            return self.validate_and_enrich_jobs(jobs)
        except Exception as e:
            print(f"[Indeed Scraper] Error fetching jobs: {str(e)}")
            return []

    def get_bangalore_jobs(self, keywords, start=0, target_city=None, **kwargs):
        return self.get_jobs(keywords, start=start, target_city=target_city, **kwargs)
