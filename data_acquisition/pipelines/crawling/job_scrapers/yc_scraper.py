import os
import urllib.request
import urllib.error
import json
import re
import html
import time
import random
from data_acquisition.pipelines.crawling.job_scrapers.job_metadata_extractor import extract_job_metadata
from data_acquisition.geo_config import DEFAULT_TARGET_CITY, match_target_city, get_mock_jobs
from data_acquisition.pipelines.crawling.job_scrapers.scraper_base import ScraperBase

class YCScraper(ScraperBase):
    def __init__(self, validator=None):
        super().__init__(validator=validator)
        self.app_id = os.environ.get("YC_ALGOLIA_APP_ID", "45BWZJ1SGC")
        self.api_key = os.environ.get("YC_ALGOLIA_API_KEY", "NzllNTY5MzJiZGM2OTY2ZTQwMDEzOTNhYWZiZGRjODlhYzVkNjBmOGRjNzJiMWM4ZTU0ZDlhYTZjOTJiMjlhMWFuYWx5dGljc1RhZ3M9eWNkYyZyZXN0cmljdEluZGljZXM9WUNDb21wYW55X3Byb2R1Y3Rpb24lMkNZQ0NvbXBhbnlfQnlfTGF1bmNoX0RhdGVfcHJvZHVjdGlvbiZ0YWdGaWx0ZXJzPSU1QiUyMnljZGNfcHVibGljJTIyJTVE")
        user_agent = os.environ.get("YC_USER_AGENT", os.environ.get("SCRAPER_USER_AGENT", 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'))
        self.headers = {
            'User-Agent': user_agent
        }

    def _slugify(self, name):
        if not name:
            return ""
        return re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-')

    def get_jobs(self, company_name, start=0, slug=None, target_city=None, **kwargs):
        if target_city is None:
            target_city = DEFAULT_TARGET_CITY
        if not company_name or str(company_name).strip() == "N/A":
            return []
        company_name = str(company_name).strip()
            
        if not slug:
            slug = self._slugify(company_name)
            
        url = f"https://www.ycombinator.com/companies/{slug}"
        req = urllib.request.Request(url, headers=self.headers)
        
        backoff = 1.0
        for attempt in range(3):
            try:
                self._sleep_throttle(1.0 if attempt == 0 else backoff, 2.0 if attempt == 0 else backoff+1.0)
                timeout_val = float(os.environ.get("SCRAPER_TIMEOUT", 10))
                with urllib.request.urlopen(req, timeout=timeout_val) as res:
                    html_content = res.read().decode('utf-8')
                    match = re.search(r'data-page="([^"]+)"', html_content)
                    if match:
                        json_str = html.unescape(match.group(1))
                        data = json.loads(json_str)
                        props = data.get('props', {})
                        postings = props.get('jobPostings', [])
                        
                        jobs = []
                        for p in postings:
                            if not isinstance(p, dict):
                                continue
                            loc = p.get('location', target_city) or target_city
                            city_match = match_target_city(loc, target_city)
                            if not city_match:
                                continue
                            job_url_val = p.get('url') or f"{url}/jobs"
                            job_data = {
                                "title": p.get('title', 'N/A'),
                                "company_name": company_name,
                                "job_url": job_url_val,
                                "url": job_url_val,
                                "location": loc,
                                "source": "Y Combinator"
                            }
                            job_data.update(extract_job_metadata(p.get('title', 'N/A'), raw_snippet=p.get('description', ''), extra_data=p))
                            jobs.append(job_data)
                        return self.validate_and_enrich_jobs(jobs)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                break
            except Exception:
                time.sleep(backoff)
                backoff *= 2
                continue
        if os.environ.get("MOCK_SCRAPER_FALLBACK", "false").lower() == "true":
            return self.validate_and_enrich_jobs(get_mock_jobs("Y Combinator", company_name, target_city))
        return []

    def get_bangalore_jobs(self, company_name, start=0, slug=None, target_city=None, **kwargs):
        return self.get_jobs(company_name, start=start, slug=slug, target_city=target_city, **kwargs)
