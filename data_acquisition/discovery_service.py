import os
import time
import random
try:
    from geo_config import DEFAULT_TARGET_CITY, DEFAULT_DISCOVERY_KEYWORDS, get_mock_jobs
except ImportError:
    from data_acquisition.geo_config import DEFAULT_TARGET_CITY, DEFAULT_DISCOVERY_KEYWORDS, get_mock_jobs

class CompanyDiscoveryService:
    """
    Independent module for Data Acquisition (Company Discovery).
    Discovers new companies using LinkedIn search keywords in Bangalore
    and adds shell records to the database if they don't already exist.
    """
    def __init__(self, db_manager, linkedin_scraper):
        self.db = db_manager
        self.scraper = linkedin_scraper

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
                
            print(f"\n[Discovery] Searching LinkedIn for jobs matching: '{kw}' in {target_city}...")
            if hasattr(self.scraper, "get_jobs"):
                jobs = self.scraper.get_jobs(kw, start=0, target_city=target_city) or []
            else:
                jobs = self.scraper.get_bangalore_jobs(kw, start=0, target_city=target_city) or []
            if not jobs and os.environ.get("MOCK_SCRAPER_FALLBACK", "false").lower() == "true":
                jobs = get_mock_jobs("LinkedIn", kw, target_city=target_city)
            print(f"[Discovery] Found {len(jobs)} job listings for keyword '{kw}'.")

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
                    
                self.db.merge_startup(details, [job], target_city=target_city)
                self.db.save_db()
                new_added += 1
                
                time.sleep(random.uniform(1.5, 3.0))
                
        print(f"\n[Discovery] Acquisition phase finished. Added {new_added} new startup records to database.")
