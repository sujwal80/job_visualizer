import os
import requests
from bs4 import BeautifulSoup
import urllib.parse
import time
import re
from data_acquisition.pipelines.crawling.job_scrapers.job_metadata_extractor import extract_job_metadata
from data_acquisition.geo_config import DEFAULT_TARGET_CITY, match_target_city
from data_acquisition.pipelines.crawling.job_scrapers.scraper_base import ScraperBase

class HiristScraper(ScraperBase):
    """
    Scraper module to find job openings via Hirist.tech.
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

        url = "https://www.hirist.tech/api/v2/search/jobs"
        params = {
            "query": keywords,
            "location": target_city,
            "start": start
        }

        try:
            res = self._get_with_retry(url, params=params)
            if not res or res.status_code != 200:
                return self._fetch_via_html(keywords, target_city)

            data = res.json()
            job_list = data.get("jobs", []) or data.get("data", [])
            jobs = []

            for item in job_list:
                if not isinstance(item, dict):
                    continue

                title = item.get("title") or item.get("job_title") or "N/A"
                comp_name = item.get("company_name") or keywords
                location = item.get("location") or target_city

                if not self._match_city(location, target_city):
                    continue

                job_url = item.get("url") or item.get("job_url") or f"https://www.hirist.tech/search/{urllib.parse.quote(keywords)}"
                if job_url.startswith('/'):
                    job_url = f"https://www.hirist.tech{job_url}"

                job_data = {
                    "title": str(title).strip(),
                    "company_name": str(comp_name).strip(),
                    "job_url": str(job_url).strip(),
                    "location": str(location).strip(),
                    "source": "Hirist"
                }
                snippet = item.get("description") or item.get("job_description") or ""
                job_data.update(extract_job_metadata(str(title).strip(), raw_snippet=str(snippet), extra_data=item))
                jobs.append(job_data)

            return self.validate_and_enrich_jobs(jobs)
        except Exception as e:
            print(f"[Hirist Scraper] API error: {str(e)}")
            return self.validate_and_enrich_jobs(self._fetch_via_html(keywords, target_city))

    def _fetch_via_html(self, keywords, target_city):
        try:
            slug = re.sub(r'[^a-z0-9]+', '-', keywords.lower()).strip('-')
            url = f"https://www.hirist.tech/search/{slug}"

            res = self._get_with_retry(url)
            if not res or res.status_code != 200:
                return []

            soup = BeautifulSoup(res.text, 'html.parser')
            job_cards = soup.find_all('div', class_=lambda x: x and ('job-item' in x or 'job-card' in x))
            jobs = []

            for card in job_cards:
                title_el = card.find('a', class_=lambda x: x and 'title' in x) or card.find('h3')
                comp_el = card.find('span', class_=lambda x: x and 'company' in x)
                loc_el = card.find('span', class_=lambda x: x and 'location' in x)

                if not title_el:
                    continue

                title = title_el.text.strip()
                comp_name = comp_el.text.strip() if comp_el else keywords
                location = loc_el.text.strip() if loc_el else target_city

                if not self._match_city(location, target_city):
                    continue

                href = title_el.get('href', url) if title_el.name == 'a' else url
                if href.startswith('/'):
                    job_url = f"https://www.hirist.tech{href}"
                else:
                    job_url = href

                job_data = {
                    "title": str(title).strip(),
                    "company_name": str(comp_name).strip(),
                    "job_url": str(job_url).strip(),
                    "location": str(location).strip(),
                    "source": "Hirist"
                }
                job_data.update(extract_job_metadata(str(title).strip(), raw_snippet=card.text.strip()))
                jobs.append(job_data)

            return jobs
        except Exception:
            return []

    def get_bangalore_jobs(self, keywords, start=0, target_city=None, **kwargs):
        return self.get_jobs(keywords, start=start, target_city=target_city, **kwargs)
