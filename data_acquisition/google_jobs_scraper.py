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

try:
    from geo_config import DEFAULT_TARGET_CITY, match_target_city
except ImportError:
    from data_acquisition.geo_config import DEFAULT_TARGET_CITY, match_target_city

class GoogleJobsScraper:
    """
    Scraper module to find job openings via Google Jobs / Search SERP queries.
    Supports both direct web search parsing and optional SerpAPI integration.
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

    def _sleep_throttle(self, min_s=1.5, max_s=3.0):
        mult = float(os.environ.get("DELAY_MULTIPLIER", 1.0))
        time.sleep(random.uniform(min_s, max_s) * mult)

    def get_bangalore_jobs(self, company_name, start=0, target_city=None, **kwargs):
        if target_city is None:
            target_city = DEFAULT_TARGET_CITY
        if not company_name or company_name == "N/A":
            return []
            
        # 1. Check if SerpAPI key is available for official Google Jobs API
        serp_key = os.environ.get("SERPAPI_API_KEY")
        if serp_key:
            return self._fetch_via_serpapi(company_name, serp_key, target_city)
            
        # 2. Fallback to resilient search query parsing
        return self._fetch_via_web_search(company_name, target_city)

    def _request_with_retry(self, method, url, **kwargs):
        backoff = 1.0
        for attempt in range(3):
            try:
                self._sleep_throttle()
                res = requests.request(method, url, proxies=self._get_proxies(), **kwargs)
                if res.status_code == 429 or res.status_code >= 500:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                return res
            except Exception:
                time.sleep(backoff)
                backoff *= 2
        return None

    def _fetch_via_serpapi(self, company_name, api_key, target_city):
        url = "https://serpapi.com/search.json"
        params = {
            "engine": "google_jobs",
            "q": f"{company_name} jobs {target_city}",
            "api_key": api_key
        }
        try:
            res = self._request_with_retry("get", url, params=params, timeout=10)
            if res and res.status_code == 200:
                data = res.json()
                jobs = []
                for j in data.get("jobs_results", []):
                    loc = j.get("location", target_city)
                    city_match = match_target_city(loc, target_city)
                    if not city_match:
                        continue
                    job_data = {
                        "title": j.get("title", "N/A"),
                        "company_name": company_name,
                        "job_url": j.get("share_link") or j.get("apply_options", [{}])[0].get("link", ""),
                        "location": loc,
                        "source": "Google Jobs"
                    }
                    job_data.update(extract_job_metadata(j.get("title", "N/A"), raw_snippet=j.get("description", ""), extra_data=j))
                    jobs.append(job_data)
                return jobs
        except Exception as e:
            print(f"[Google Jobs Scraper] SerpAPI error: {e}")
        return []

    def _fetch_via_web_search(self, company_name, target_city):
        query = f'"{company_name}" jobs {target_city} hiring'
        url = "https://html.duckduckgo.com/html/"
        data = {"q": query}
        
        try:
            res = self._request_with_retry("post", url, headers=self.headers, data=data, timeout=10)
            if not res or res.status_code != 200:
                return []
                
            soup = BeautifulSoup(res.text, 'html.parser')
            results = soup.find_all('div', class_='result')
            jobs = []
            
            job_keywords = ["engineer", "developer", "manager", "designer", "analyst", "sde", "lead", "specialist", "exec", "intern"]
            
            for r in results[:8]:
                title_el = r.find('a', class_='result__a')
                snippet_el = r.find('a', class_='result__snippet')
                
                if not title_el:
                    continue
                    
                raw_title = title_el.text.strip()
                link = title_el['href']
                
                if "uddg=" in link:
                    parsed = urllib.parse.urlparse(link)
                    qs = urllib.parse.parse_qs(parsed.query)
                    link = qs.get('uddg', [link])[0]
                    
                lower_title = raw_title.lower()
                if any(k in lower_title for k in job_keywords) and company_name.lower().split()[0] in lower_title:
                    clean_title = re.split(r'[-|–|at|@]|\bjob\b|\bcareers\b', raw_title, flags=re.IGNORECASE)[0].strip()
                    if len(clean_title) > 3:
                        job_data = {
                            "title": clean_title,
                            "company_name": company_name,
                            "job_url": link,
                            "location": target_city,
                            "source": "Google Search"
                        }
                        snippet_text = snippet_el.text.strip() if snippet_el else ""
                        job_data.update(extract_job_metadata(clean_title, raw_snippet=snippet_text))
                        jobs.append(job_data)
            return jobs
        except Exception as e:
            print(f"[Google Jobs Scraper] Web search error: {e}")
            return []
