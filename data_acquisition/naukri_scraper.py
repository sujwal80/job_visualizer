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

class NaukriScraper:
    """
    Scraper module to find job openings via Naukri.com.
    """
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "en-US,en;q=0.5",
            "appid": "109",
            "systemid": "109"
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
        if not keywords or str(keywords).strip() == "N/A":
            return []
        keywords = str(keywords).strip()

        url = "https://www.naukri.com/jobapi/v3/search"
        api_loc = "bangalore" if target_city.lower() == "bengaluru" else target_city.lower()
        params = {
            "noOfResults": 20,
            "urlType": "search_by_keyword",
            "searchType": "adv",
            "keyword": keywords,
            "location": api_loc,
            "pageNo": (start // 20) + 1
        }

        try:
            res = self._get_with_retry(url, params=params)
            if not res or res.status_code != 200:
                return self._fetch_via_html(keywords, target_city)

            data = res.json()
            job_details = data.get("jobDetails", [])
            jobs = []

            for item in job_details:
                if not isinstance(item, dict):
                    continue

                title = item.get("title") or "N/A"
                comp_name = item.get("companyName") or keywords
                placeholders = item.get("placeholders", [])
                location = target_city
                for p in placeholders:
                    if isinstance(p, dict) and p.get("type") == "location":
                        location = p.get("label", target_city)
                        break

                if not self._match_city(location, target_city):
                    continue

                job_url = item.get("jdURL") or f"https://www.naukri.com/{urllib.parse.quote(keywords)}-jobs-in-{urllib.parse.quote(target_city)}"

                job_data = {
                    "title": str(title).strip(),
                    "company_name": str(comp_name).strip(),
                    "job_url": str(job_url).strip(),
                    "location": str(location).strip(),
                    "source": "Naukri"
                }
                job_data.update(extract_job_metadata(str(title).strip(), raw_snippet=str(item.get("jobDescription") or ""), extra_data=item))
                jobs.append(job_data)

            return jobs
        except Exception as e:
            print(f"[Naukri Scraper] API error: {str(e)}")
            return self._fetch_via_html(keywords, target_city)

    def _fetch_via_html(self, keywords, target_city):
        try:
            slug = re.sub(r'[^a-z0-9]+', '-', str(keywords).lower()).strip('-')
            city_slug = re.sub(r'[^a-z0-9]+', '-', str(target_city).lower()).strip('-')
            url = f"https://www.naukri.com/{slug}-jobs-in-{city_slug}"

            res = self._get_with_retry(url)
            if not res or res.status_code != 200:
                return []

            soup = BeautifulSoup(res.text, 'html.parser')
            job_tuples = soup.find_all('article', class_=lambda x: x and 'jobTuple' in x)
            jobs = []

            for article in job_tuples:
                title_el = article.find('a', class_=lambda x: x and 'title' in x)
                comp_el = article.find('a', class_=lambda x: x and 'comp-name' in x)
                loc_el = article.find('span', class_=lambda x: x and 'locWdth' in x)

                if not title_el:
                    continue

                title = title_el.text.strip()
                comp_name = comp_el.text.strip() if comp_el else keywords
                location = loc_el.text.strip() if loc_el else target_city

                if not self._match_city(location, target_city):
                    continue

                job_url = title_el.get('href', url)

                job_data = {
                    "title": str(title).strip(),
                    "company_name": str(comp_name).strip(),
                    "job_url": str(job_url).strip(),
                    "location": str(location).strip(),
                    "source": "Naukri"
                }
                snippet_text = article.text.strip() if article else ""
                job_data.update(extract_job_metadata(str(title).strip(), raw_snippet=snippet_text))
                jobs.append(job_data)

            return jobs
        except Exception:
            return []
