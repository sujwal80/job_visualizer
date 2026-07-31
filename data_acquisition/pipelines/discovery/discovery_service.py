import os
import time
import random
from data_acquisition.geo_config import DEFAULT_TARGET_CITY, DEFAULT_DISCOVERY_KEYWORDS, get_mock_jobs

class CompanyDiscoveryService:
    """
    Independent module for Data Acquisition (Company Discovery).
    Discovers new companies using LinkedIn search keywords in Bangalore
    and adds shell records to the database if they don't already exist.
    """
    def __init__(self, db_manager, linkedin_scraper, validator=None):
        self.db = db_manager
        self.scraper = linkedin_scraper
        self.validator = validator

    def discover_new_companies(self, keywords_list=None, max_new_companies=None, target_city=None):
        if target_city is None:
            target_city = DEFAULT_TARGET_CITY
        if keywords_list is None:
            env_kw = os.environ.get("DISCOVERY_KEYWORDS")
            if env_kw:
                keywords_list = [k.strip() for k in env_kw.split(",") if k.strip()]
            else:
                keywords_list = DEFAULT_DISCOVERY_KEYWORDS

        print("\n=== STARTING COMPANY DISCOVERY PHASE (ACQUISITION) ===")
        print(f"[Discovery] Target Keywords: {keywords_list}, City: {target_city}, Max New Companies: {'Unlimited' if max_new_companies is None else max_new_companies}")
        
        new_added = 0
        for kw in keywords_list:
            if max_new_companies is not None and new_added >= max_new_companies:
                break
                
            start_offset = 0
            empty_pages = 0
            no_new_pages_count = 0
            while (max_new_companies is None or new_added < max_new_companies) and start_offset <= 100:
                print(f"\n[Discovery] Searching LinkedIn for jobs matching: '{kw}' (offset {start_offset}) in {target_city}...")
                if hasattr(self.scraper, "get_jobs"):
                    jobs = self.scraper.get_jobs(kw, start=start_offset, target_city=target_city) or []
                else:
                    jobs = self.scraper.get_bangalore_jobs(kw, start=start_offset, target_city=target_city) or []
                if not jobs and os.environ.get("MOCK_SCRAPER_FALLBACK", "false").lower() == "true":
                    jobs = get_mock_jobs("LinkedIn", kw, target_city=target_city)
                print(f"[Discovery] Found {len(jobs)} job listings for keyword '{kw}' (offset {start_offset}).")

                if not jobs:
                    empty_pages += 1
                    if empty_pages >= 2:
                        break
                    start_offset += 10
                    continue

                empty_pages = 0
                page_added = 0

                for job in jobs:
                    if max_new_companies is not None and new_added >= max_new_companies:
                        break
                    if not isinstance(job, dict):
                        continue
                        
                    comp_name = str(job.get("company_name") or "").strip()
                    comp_slug = str(job.get("company_slug") or "").strip()
                    
                    if not comp_name or comp_name == "N/A":
                        continue
                        
                    existing = self.db.find_startup(comp_name, logo_domain=None, target_city=target_city)
                    if existing:
                        continue
                        
                    print(f"[Discovery] Discovered NEW company candidate: '{comp_name}' (slug: {comp_slug})")
                    
                    details = None
                    if comp_slug and hasattr(self.scraper, "get_company_details"):
                        details = self.scraper.get_company_details(comp_slug, target_city=target_city)
                        
                    if not details:
                        job_title = str(job.get('title') or 'Open Roles')
                        loc_val = str(job.get("location") or target_city)
                        details = {
                            "name": comp_name,
                            "website": "",
                            "industry": "Software Development",
                            "head_count": 15,
                            "headquarters": target_city,
                            "description": f"Innovative startup in {target_city} hiring for {job_title}.",
                            "bangalore_address": loc_val,
                            "office_address": loc_val,
                            "logo_domain": ""
                        }
                    else:
                        if "office_address" not in details:
                            details["office_address"] = details.get("bangalore_address") or target_city
                        
                    if not details.get("website"):
                        official_web, official_dom = self._resolve_official_company_website(comp_name, comp_slug)
                        if official_web:
                            details["website"] = official_web
                            details["logo_domain"] = official_dom
                            print(f"[Discovery] Resolved official website '{official_web}' for new startup '{comp_name}'")

                    if self.validator is not None:
                        self.validator.validate_company_status(details)
                    merged = self.db.merge_startup(details, [job], target_city=target_city)
                    if merged is not None:
                        self.db.save_db()
                        new_added += 1
                        page_added += 1
                    
                    delay_mult = float(os.environ.get("DELAY_MULTIPLIER", 0.0))
                    if delay_mult > 0:
                        time.sleep(random.uniform(1.5, 3.0) * delay_mult)

                if page_added == 0:
                    no_new_pages_count += 1
                    if no_new_pages_count >= 2:
                        break
                else:
                    no_new_pages_count = 0

                start_offset += 10
                
        print(f"\n[Discovery] Acquisition phase finished. Added {new_added} new startup records to database.")

    def _resolve_official_company_website(self, comp_name, comp_slug):
        """
        Resolves official company website and domain during discovery phase.
        Uses a hybrid strategy (Wikidata API -> Clearbit Autocomplete API -> DuckDuckGo HTML Scraper -> Template Guessing)
        with strict name matching verification guards.
        """
        import re
        import urllib.parse
        import requests
        from data_acquisition.utils.validation import validate_website_domain, is_blacklisted_domain

        def clean_comp_name(name):
            n = re.sub(r'\b(pvt|ltd|private|limited|inc|corp|llc|co)\.?\b', '', name, flags=re.IGNORECASE)
            return re.sub(r'\s+', ' ', n).strip().lower()

        def is_name_match(q_name, cand_name):
            q_clean = clean_comp_name(q_name)
            c_clean = clean_comp_name(cand_name)
            if not q_clean or not c_clean:
                return False
            if q_clean in c_clean or c_clean in q_clean:
                return True
            q_tokens = set(q_clean.split())
            c_tokens = set(c_clean.split())
            if q_tokens & c_tokens:
                return True
            return False

        # Tier 1: Wikidata API Lookup
        search_url = "https://www.wikidata.org/w/api.php"
        headers = {"User-Agent": "JobVisualizerBot/1.0 (singhujwal@gmail.com) Python-Requests"}
        try:
            r = requests.get(search_url, params={
                "action": "wbsearchentities", "search": comp_name, "language": "en", "format": "json"
            }, headers=headers, timeout=4)
            results = r.json().get("search", [])
            if results:
                first_res = results[0]
                if is_name_match(comp_name, first_res.get("label", "")):
                    entity_id = first_res["id"]
                    r_entities = requests.get(search_url, params={
                        "action": "wbgetentities", "ids": entity_id, "format": "json", "props": "claims"
                    }, headers=headers, timeout=4)
                    claims = r_entities.json().get("entities", {}).get(entity_id, {}).get("claims", {})
                    p856 = claims.get("P856", [])
                    if p856:
                        cand_url = p856[0].get("mainsnak", {}).get("datavalue", {}).get("value")
                        if cand_url and cand_url.startswith(("http://", "https://")):
                            is_active, healed_url, _ = validate_website_domain(cand_url)
                            if is_active and healed_url:
                                parsed = urllib.parse.urlparse(healed_url)
                                netloc = parsed.netloc.lower()
                                if netloc.startswith("www."):
                                    netloc = netloc[4:]
                                if not is_blacklisted_domain(netloc):
                                    return healed_url, netloc
        except Exception:
            pass

        # Tier 2: Clearbit Autocomplete API
        clearbit_url = f"https://autocomplete.clearbit.com/v1/companies/suggest?query={urllib.parse.quote(comp_name)}"
        headers_cb = {"User-Agent": "Mozilla/5.0"}
        try:
            r_cb = requests.get(clearbit_url, headers=headers_cb, timeout=4)
            if r_cb.status_code == 200:
                for suggestion in r_cb.json()[:3]:
                    cand_name = suggestion.get("name", "")
                    if is_name_match(comp_name, cand_name):
                        domain = suggestion.get("domain")
                        if domain and not is_blacklisted_domain(domain):
                            cand_url = f"https://www.{domain}"
                            is_active, healed_url, _ = validate_website_domain(cand_url)
                            if is_active and healed_url:
                                return healed_url, domain
        except Exception:
            pass

        # Tier 3: DuckDuckGo HTML Search
        query = f"{comp_name} official website homepage"
        ddg_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        headers_ddg = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        blacklist = ["linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com", "wikipedia.org", "wikidata.org", "naukri.com", "indeed.com", "glassdoor.com", "wellfound.com", "crunchbase.com", "ycombinator.com"]
        try:
            r_ddg = requests.get(ddg_url, headers=headers_ddg, timeout=4)
            if r_ddg.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r_ddg.text, "html.parser")
                for link in soup.find_all("a", class_="result__url")[:3]:
                    raw_href = link.get("href") or ""
                    if raw_href.startswith("//"):
                        raw_href = "https:" + raw_href
                    if "/l/?" in raw_href:
                        qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_href).query)
                        href = qs.get("uddg", [raw_href])[0]
                    else:
                        href = raw_href
                    domain = urllib.parse.urlparse(href).netloc.lower()
                    if domain.startswith("www."):
                        domain = domain[4:]
                    if not any(b in domain for b in blacklist) and not is_blacklisted_domain(domain):
                        is_active, healed_url, _ = validate_website_domain(href)
                        if is_active and healed_url:
                            return healed_url, domain
        except Exception:
            pass

        # Tier 4: Template Guess Fallback (as last resort)
        clean_slug = str(comp_slug or "").strip().lower()
        if not clean_slug:
            clean_slug = re.sub(r'[^a-z0-9]', '', str(comp_name or "").lower())

        if clean_slug and not is_blacklisted_domain(clean_slug):
            for tld in ["com", "ai", "co", "tech", "io"]:
                cand = f"https://www.{clean_slug}.{tld}"
                is_active, healed_url, _ = validate_website_domain(cand)
                if is_active and healed_url:
                    parsed = urllib.parse.urlparse(healed_url)
                    netloc = parsed.netloc.lower()
                    if netloc.startswith("www."):
                        netloc = netloc[4:]
                    if not is_blacklisted_domain(netloc):
                        return healed_url, netloc

        return "", ""
