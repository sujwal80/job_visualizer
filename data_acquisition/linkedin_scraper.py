import os
import requests
from bs4 import BeautifulSoup
import re
import urllib.parse
import time
import random
try:
    from job_metadata_extractor import extract_job_metadata
except ImportError:
    from data_acquisition.job_metadata_extractor import extract_job_metadata

try:
    from geo_config import DEFAULT_TARGET_CITY, match_target_city
except ImportError:
    from data_acquisition.geo_config import DEFAULT_TARGET_CITY, match_target_city

class LinkedInScraper:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        }
        
    def _get_proxies(self):
        proxy = os.environ.get("PROXY_URL")
        return {"http": proxy, "https": proxy} if proxy else None

    def _sleep_throttle(self, min_s=1.0, max_s=2.0):
        mult = float(os.environ.get("DELAY_MULTIPLIER", 1.0))
        time.sleep(random.uniform(min_s, max_s) * mult)

    def _get_with_retry(self, url, params=None, allow_redirects=True, timeout=10):
        backoff = 1.0
        for attempt in range(3):
            try:
                self._sleep_throttle()
                res = requests.get(url, headers=self.headers, params=params, proxies=self._get_proxies(), allow_redirects=allow_redirects, timeout=timeout)
                if res.status_code == 429 or res.status_code >= 500:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                return res
            except Exception:
                time.sleep(backoff)
                backoff *= 2
        return None

    def get_bangalore_jobs(self, keywords, start=0, target_city=None, **kwargs):
        if target_city is None:
            target_city = DEFAULT_TARGET_CITY
        """
        Fetch jobs from the public guest jobs API.
        Returns a list of dicts: {title, company_name, company_slug, job_url, location}
        """
        url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        params = {
            "keywords": keywords,
            "location": target_city,
            "start": start
        }
        
        try:
            response = self._get_with_retry(url, params=params)
            if not response or response.status_code != 200:
                status = response.status_code if response else "None"
                print(f"[LinkedIn Scraper] Jobs fetch failed with status code {status}")
                return []
                
            soup = BeautifulSoup(response.text, 'html.parser')
            job_cards = soup.find_all('li')
            jobs = []
            
            for card in job_cards:
                title_el = card.find('h3', class_='base-search-card__title')
                company_el = card.find('a', class_='hidden-nested-link')
                link_el = card.find('a', class_='base-card__full-link')
                loc_el = card.find('span', class_='job-search-card__location')
                
                title = title_el.text.strip() if title_el else "N/A"
                company_name = company_el.text.strip() if company_el else "N/A"
                company_url = company_el['href'] if company_el else ""
                job_url = link_el['href'] if link_el else "N/A"
                location = loc_el.text.strip() if loc_el else target_city
                
                # Strict city location filtering per grill-me decision
                loc_lower = location.lower()
                city_match = match_target_city(location, target_city)
                if not city_match:
                    continue
                
                # Extract company slug
                company_slug = ""
                if company_url:
                    parsed_url = urllib.parse.urlparse(company_url)
                    path_parts = parsed_url.path.strip('/').split('/')
                    if len(path_parts) >= 2 and path_parts[0] == 'company':
                        company_slug = path_parts[1]
                
                if company_slug:
                    job_data = {
                        "title": title,
                        "company_name": company_name,
                        "company_slug": company_slug,
                        "job_url": job_url,
                        "location": location
                    }
                    snippet_text = card.text.strip() if card else ""
                    job_data.update(extract_job_metadata(title, raw_snippet=snippet_text))
                    jobs.append(job_data)
            
            return jobs
        except Exception as e:
            print(f"[LinkedIn Scraper] Error fetching jobs: {str(e)}")
            return []

    def get_company_details(self, company_slug, target_city=None):
        if target_city is None:
            target_city = DEFAULT_TARGET_CITY
        """
        Fetch company metadata from public profile.
        Returns details dict.
        """
        url = f"https://www.linkedin.com/company/{company_slug}"
        try:
            response = self._get_with_retry(url, allow_redirects=True)
            if not response or response.status_code != 200:
                status = response.status_code if response else "None"
                print(f"[LinkedIn Scraper] Company profile fetch failed for '{company_slug}' with status {status}")
                return None
                
            # Check for redirect to login
            if "signup" in response.url or "login" in response.url:
                print(f"[LinkedIn Scraper] Redirected to login page for company '{company_slug}'")
                return None
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 1. Parse Name
            name = "N/A"
            top_card = soup.find('section', class_='top-card-layout')
            if top_card:
                name_el = top_card.find('h1')
                name = name_el.text.strip() if name_el else "N/A"
            
            # 2. Parse Description (from meta tag first, then fallback to About)
            desc_meta = soup.find('meta', {'name': 'description'})
            description = desc_meta['content'] if desc_meta else ""
            if not description:
                desc_meta_og = soup.find('meta', {'property': 'og:description'})
                description = desc_meta_og['content'] if desc_meta_og else ""
            
            # 3. Parse Logo Domain or Delayed Image
            logo_domain = ""
            if top_card:
                img_el = top_card.find('img', class_='artdeco-entity-image')
                if img_el:
                    logo_src = img_el.get('src') or img_el.get('data-delayed-url') or ""
            
            # 4. Parse DL Metadata (Website, Industry, Size, Headquarters)
            website = ""
            industry = "Software"
            headcount_str = ""
            headquarters = ""
            
            dl = soup.find('dl')
            if dl:
                dts = dl.find_all('dt')
                dds = dl.find_all('dd')
                for t, d in zip(dts, dds):
                    dt_text = " ".join(t.text.split()).lower()
                    dd_text = " ".join(d.text.split())
                    
                    if "website" in dt_text:
                        a_el = d.find('a')
                        website = a_el['href'] if a_el else dd_text
                        if "linkedin.com/redir" in website:
                            parsed_web = urllib.parse.urlparse(website)
                            qs = urllib.parse.parse_qs(parsed_web.query)
                            website = qs.get('url', [website])[0]
                    elif "industry" in dt_text:
                        industry = dd_text
                    elif "company size" in dt_text:
                        headcount_str = dd_text
                    elif "headquarters" in dt_text:
                        headquarters = dd_text
                        
            headcount = self._parse_headcount(headcount_str)
            
            # 5. Extract Office Address matching target_city
            bangalore_address = ""
            loc_section = soup.find('section', class_=lambda x: x and 'locations' in x.split())
            if loc_section:
                loc_items = loc_section.find_all('li')
                for item in loc_items:
                    addr_text = " ".join(item.text.split())
                    addr_text = addr_text.replace("Get directions", "").strip()
                    heading_el = item.find('h3')
                    heading = heading_el.text.strip() if heading_el else ""
                    if heading:
                        addr_text = addr_text.replace(heading, "").strip()
                        
                    city_match = match_target_city(addr_text, target_city)
                    if city_match:
                        bangalore_address = addr_text
                        break
            
            if not bangalore_address and headquarters:
                hq_match = match_target_city(headquarters, target_city)
                if hq_match:
                    bangalore_address = headquarters
                else:
                    bangalore_address = target_city
                
            return {
                "name": name,
                "website": website,
                "industry": industry,
                "head_count": headcount,
                "headquarters": headquarters,
                "description": description,
                "bangalore_address": bangalore_address,
                "logo_domain": self._extract_domain(website)
            }
        except Exception as e:
            print(f"[LinkedIn Scraper] Error fetching company details for '{company_slug}': {str(e)}")
            return None

    def _parse_headcount(self, headcount_str):
        if not headcount_str:
            return 10
        headcount_str = headcount_str.replace(',', '')
        numbers = [int(s) for s in re.findall(r'\b\d+\b', headcount_str)]
        if len(numbers) == 2:
            return (numbers[0] + numbers[1]) // 2
        elif len(numbers) == 1:
            return numbers[0]
        return 10

    def _extract_domain(self, website):
        if not website:
            return ""
        try:
            parsed = urllib.parse.urlparse(website)
            domain = parsed.netloc.lower()
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception:
            return ""
