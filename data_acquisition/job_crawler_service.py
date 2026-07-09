import os
import time
import random

try:
    from geo_config import get_mock_jobs
except ImportError:
    from data_acquisition.geo_config import get_mock_jobs

class JobCrawlerService:
    """
    Unified job crawling coordinator module.
    Runs multiple independent job scraper sources (LinkedIn, Instahyre, Google Jobs, YC, ATS)
    and merges validated openings into the company record.
    """
    def __init__(self, db_manager, scrapers_dict):
        """
        scrapers_dict format: {"Source Name": scraper_instance}
        """
        self.db = db_manager
        self.scrapers = scrapers_dict

    def crawl_jobs_for_company(self, company_record, target_city="Bengaluru"):
        if not isinstance(company_record, dict):
            return 0
        comp_name = str(company_record.get("name") or "N/A").strip()
        if not comp_name or comp_name == "N/A":
            return 0
            
        norm_target = self.db._normalize_text(comp_name)
        all_matching_jobs = []
        
        print(f"\n[Job Crawler Service] Crawling multi-source jobs for '{comp_name}' in {target_city}...")
        
        for source_name, scraper in self.scrapers.items():
            try:
                jobs = scraper.get_bangalore_jobs(comp_name, start=0, target_city=target_city) or []
                if not jobs and os.environ.get("MOCK_SCRAPER_FALLBACK", "false").lower() == "true":
                    jobs = get_mock_jobs(source_name, keywords=comp_name, target_city=target_city, company_name=comp_name)
                source_matches = 0
                
                for job in jobs:
                    if not isinstance(job, dict):
                        continue
                    norm_job_comp = self.db._normalize_text(str(job.get("company_name") or ""))
                    if norm_target and norm_job_comp:
                        if norm_target in norm_job_comp or norm_job_comp in norm_target:
                            all_matching_jobs.append(job)
                            source_matches += 1
                            
                if source_matches > 0:
                    print(f"  [{source_name}] Found {source_matches} verified job openings.")
            except Exception as e:
                print(f"  [{source_name}] Error crawling jobs: {e}")
                
        initial_job_count = len(company_record.get("job_openings") or [])
        if all_matching_jobs:
            self.db._merge_job_openings(company_record, all_matching_jobs)
            
        new_jobs = len(company_record.get("job_openings") or []) - initial_job_count
        if new_jobs > 0:
            print(f"  -> Merged {new_jobs} new unique job openings for '{comp_name}'.")
        return new_jobs
