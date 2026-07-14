import os
import sys
import time
import random

_curr_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(_curr_dir)
sys.path.append(os.path.join(_curr_dir, "job_scrapers"))
sys.path.append(os.path.join(_curr_dir, "tagging"))

from job_scrapers import LinkedInScraper
from db_manager import DBManager
from discovery_service import CompanyDiscoveryService
from tagging import LogoEnricher, LocationEnricher, run_classification
from job_validator import JobValidator
try:
    from geo_config import DEFAULT_TARGET_CITY
except ImportError:
    from data_acquisition.geo_config import DEFAULT_TARGET_CITY

def load_env_file():
    workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(workspace_root, ".env")
    if os.path.exists(env_path):
        print(f"[Env Loader] Loading variables from: {env_path}")
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")

def run_pipeline(run_discovery=True, run_tagging=True, run_validation=True, max_discovery=None, max_tagging=None, max_validation=None, target_city=None, db_path=None, force=False):
    if target_city is None:
        target_city = DEFAULT_TARGET_CITY
    load_env_file()
    workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if db_path is None:
        env_db_path = os.environ.get("STARTUP_DB_PATH", "backend/startups.json")
        if os.path.isabs(env_db_path):
            db_path = env_db_path
        else:
            db_path = os.path.join(workspace_root, env_db_path)
    
    print("==========================================================")
    print(f"=== {target_city.upper()} STARTUP DATA ACQUISITION & TAGGING PIPELINE ===")
    print(f"Database Path: {db_path}")
    print("==========================================================")
    
    # 0. Initialize components
    db = DBManager(db_path)
    validator = JobValidator(db)
    linkedin_scraper = LinkedInScraper(validator=validator)
    
    # 1. Acquisition Phase (Company Discovery)
    if run_discovery:
        discovery = CompanyDiscoveryService(db, linkedin_scraper, validator=validator)
        discovery.discover_new_companies(max_new_companies=max_discovery, target_city=target_city)
        
    # 2. Tagging & Enrichment Phase
    if run_tagging:
        print("\n=== STARTING DATA TAGGING & ENRICHMENT PHASE ===")
        logo_enricher = LogoEnricher()
        location_enricher = LocationEnricher(db)
        
        db.load_db()
        startups_to_tag = list(db.startups)
        total_startups = len(startups_to_tag)
        print(f"[Tagging Phase] Loaded {total_startups} startups from DB for enrichment.")
        
        processed = 0
        for startup in startups_to_tag:
            processed += 1
            if max_tagging and processed > max_tagging:
                print(f"[Tagging Phase] Reached max_tagging limit ({max_tagging}). Stopping tagging loop.")
                break
                
            comp_name = startup.get("name", "N/A")
            comp_id = startup.get("id")
            print(f"\n[Enriching {processed}/{total_startups}] Company: '{comp_name}' (ID: {comp_id})")
            
            if not comp_name or comp_name == "N/A":
                continue
                
            startup_copy = dict(startup)
            logo_changed = logo_enricher.enrich(startup_copy)
            loc_changed = location_enricher.enrich(startup_copy, target_city=target_city)
            
            if logo_changed or loc_changed:
                with db.file_lock(db.db_path):
                    db.load_db()
                    record = next((x for x in db.startups if x.get("id") == comp_id), None)
                    if record:
                        if logo_changed:
                            record["logo_domain"] = startup_copy.get("logo_domain")
                            record["logo_svg_url"] = startup_copy.get("logo_svg_url")
                        if loc_changed:
                            record["lat"] = startup_copy.get("lat")
                            record["lng"] = startup_copy.get("lng")
                            record["city"] = startup_copy.get("city")
                            if "is_remote_office" in startup_copy:
                                record["is_remote_office"] = startup_copy.get("is_remote_office")
                            if "remote_office_distance_km" in startup_copy:
                                record["remote_office_distance_km"] = startup_copy.get("remote_office_distance_km")
                        db.save_db()
                
            if not os.environ.get("NO_RATE_LIMIT"):
                time.sleep(random.uniform(1.0, 2.0))
            
        print("\n=== TAGGING & ENRICHMENT PHASE COMPLETED ===")
        
    # 3. Validation & Pruning Phase
    if run_validation:
        validator.validate_and_prune(max_startups=max_validation)
        
    # 4. Industry Classification Phase
    if run_tagging:
        print("\n=== STARTING AUTOMATIC INDUSTRY CLASSIFICATION ===")
        run_classification(db_path, force=force)
        print("=== INDUSTRY CLASSIFICATION COMPLETED ===")
        
    print(f"\nPipeline execution finished successfully. Total startups in DB: {len(db.startups)}")

if __name__ == "__main__":
    args = sys.argv[1:]
    test_mode = "--test" in args
    if "--mock" in args:
        os.environ["MOCK_SCRAPER_FALLBACK"] = "true"
    
    target_city = os.environ.get("TARGET_CITY", DEFAULT_TARGET_CITY)
    if "--city" in args:
        idx = args.index("--city")
        if idx + 1 < len(args):
            target_city = args[idx + 1]
            
    db_path = None
    if "--db-path" in args:
        idx = args.index("--db-path")
        if idx + 1 < len(args):
            db_path = args[idx + 1]

    max_discovery_arg = None
    if "--max-discovery" in args:
        idx = args.index("--max-discovery")
        if idx + 1 < len(args):
            val = args[idx + 1].strip()
            if val.lower() not in ["none", "all", "unlimited"]:
                try:
                    max_discovery_arg = int(val)
                except ValueError:
                    max_discovery_arg = None

    force_classification = "--force-classification" in args or "--force" in args

    if test_mode:
        print(f"[CLI] Running in TEST MODE for city '{target_city}' (max 1 discovery, max 2 tagging, max 2 validation)...")
        run_pipeline(run_discovery=True, run_tagging=True, run_validation=True, max_discovery=1, max_tagging=2, max_validation=2, target_city=target_city, db_path=db_path, force=force_classification)
    else:
        run_pipeline(run_discovery=True, run_tagging=True, run_validation=True, max_discovery=max_discovery_arg, max_tagging=None, max_validation=None, target_city=target_city, db_path=db_path, force=force_classification)
