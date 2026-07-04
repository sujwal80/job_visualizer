import os
import urllib.request
import urllib.error
import json
import re
import html
import time
import random
try:
    from job_metadata_extractor import extract_job_metadata
except ImportError:
    from data_acquisition.job_metadata_extractor import extract_job_metadata

class YCScraper:
    def __init__(self):
        self.app_id = "45BWZJ1SGC"
        self.api_key = "NzllNTY5MzJiZGM2OTY2ZTQwMDEzOTNhYWZiZGRjODlhYzVkNjBmOGRjNzJiMWM4ZTU0ZDlhYTZjOTJiMjlhMWFuYWx5dGljc1RhZ3M9eWNkYyZyZXN0cmljdEluZGljZXM9WUNDb21wYW55X3Byb2R1Y3Rpb24lMkNZQ0NvbXBhbnlfQnlfTGF1bmNoX0RhdGVfcHJvZHVjdGlvbiZ0YWdGaWx0ZXJzPSU1QiUyMnljZGNfcHVibGljJTIyJTVE"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        }

    def _sleep_throttle(self, min_s=1.0, max_s=2.0):
        mult = float(os.environ.get("DELAY_MULTIPLIER", 1.0))
        time.sleep(random.uniform(min_s, max_s) * mult)

    def _slugify(self, name):
        if not name:
            return ""
        return re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-')

    def get_bangalore_jobs(self, company_name, start=0, slug=None, target_city="Bengaluru", **kwargs):
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
                with urllib.request.urlopen(req, timeout=10) as res:
                    html_content = res.read().decode('utf-8')
                    match = re.search(r'data-page="([^"]+)"', html_content)
                    if match:
                        json_str = html.unescape(match.group(1))
                        data = json.loads(json_str)
                        props = data.get('props', {})
                        postings = props.get('jobPostings', [])
                        
                        jobs = []
                        for p in postings:
                            loc = p.get('location', target_city)
                            loc_lower = loc.lower()
                            city_match = target_city.lower() in loc_lower or ("bengaluru" in loc_lower if target_city.lower() == "bangalore" else False) or ("bangalore" in loc_lower if target_city.lower() == "bengaluru" else False)
                            if not city_match:
                                continue
                            job_data = {
                                "title": p.get('title', 'N/A'),
                                "company_name": company_name,
                                "job_url": p.get('url') or f"{url}/jobs",
                                "location": loc,
                                "source": "Y Combinator"
                            }
                            job_data.update(extract_job_metadata(p.get('title', 'N/A'), raw_snippet=p.get('description', ''), extra_data=p))
                            jobs.append(job_data)
                        return jobs
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
                break
        return []
