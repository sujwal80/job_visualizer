import os
import requests
from bs4 import BeautifulSoup
import urllib.parse
import time
import re
from data_acquisition.pipelines.crawling.job_scrapers.job_metadata_extractor import extract_job_metadata
from data_acquisition.geo_config import DEFAULT_TARGET_CITY, match_target_city
from data_acquisition.pipelines.crawling.job_scrapers.scraper_base import ScraperBase

class CutshortScraper(ScraperBase):
    """
    Scraper module to find job openings via Cutshort.io.
    """
    def __init__(self, validator=None):
        super().__init__(validator=validator)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "en-US,en;q=0.5"
        }

    def _get_proxies(self):
        proxy = os.environ.get("PROXY_URL")
        return {"http": proxy, "https": proxy} if proxy else None

    def _match_city(self, loc, target_city):
        return match_target_city(loc, target_city)

    def _slugify(self, name):
        if not name:
            return ""
        return re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-')

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
        if not keywords or str(keywords).strip() == "N/A":
            return []
        keywords = str(keywords).strip()

        slug = self._slugify(keywords)
        url = f"https://cutshort.io/company/{slug}"

        try:
            res = self._get_with_retry(url)
            if not res or res.status_code != 200:
                return []

            soup = BeautifulSoup(res.text, 'html.parser')
            job_cards = soup.find_all('div', class_=lambda x: x and ('job-card' in x or 'jobItem' in x or 'job-listing-item' in x))
            jobs = []

            for card in job_cards:
                title_el = card.find('a', class_=lambda x: x and ('title' in x or 'job-title' in x)) or card.find('h3')
                if not title_el:
                    continue

                raw_title = title_el.text.strip()
                loc_el = card.find('span', class_=lambda x: x and ('location' in x or 'city' in x))
                location = loc_el.text.strip() if loc_el else target_city

                if not self._match_city(location, target_city):
                    continue

                href = title_el.get('href', '') if title_el.name == 'a' else ''
                if not href:
                    link_el = card.find('a', href=True)
                    href = link_el['href'] if link_el else ''

                if href.startswith('/'):
                    job_url = f"https://cutshort.io{href}"
                elif href:
                    job_url = href
                else:
                    job_url = url

                job_data = {
                    "title": str(raw_title).strip(),
                    "company_name": str(keywords).strip(),
                    "job_url": str(job_url).strip(),
                    "location": str(location).strip(),
                    "source": "Cutshort"
                }
                snippet_text = card.text.strip() if card else ""
                job_data.update(extract_job_metadata(str(raw_title).strip(), raw_snippet=snippet_text))
                jobs.append(job_data)

            return self.validate_and_enrich_jobs(jobs)
        except Exception as e:
            print(f"[Cutshort Scraper] Error fetching jobs: {str(e)}")
            return []

    def get_bangalore_jobs(self, keywords, start=0, target_city=None, **kwargs):
        return self.get_jobs(keywords, start=start, target_city=target_city, **kwargs)
