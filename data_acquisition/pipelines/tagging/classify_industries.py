#!/usr/bin/env python3
"""
Standalone Industry Classification Script

Analyzes startup records in backend/startups.json and assigns accurate startup sectors:
Artificial Intelligence, Fintech, SaaS, E-commerce, HealthTech, EdTech, CleanTech, Cybersecurity, Logistics, B2B.
"""

import os
import re
import sys
import requests
import argparse
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
DATA_ACQ_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if DATA_ACQ_DIR not in sys.path:
    sys.path.insert(0, DATA_ACQ_DIR)

from db_manager import DBManager

LINKEDIN_MAPPING = {
    "IT Services and IT Consulting": "Service Industry",
    "Business Consulting and Services": "Service Industry",
    "Engineering Services": "Service Industry",
    "Financial Services": "Fintech",
    "Banking": "Fintech",
    "Investment Management": "Fintech",
    "Venture Capital and Private Equity Principals": "Fintech",
    "Hospitals and Health Care": "HealthTech",
    "Biotechnology": "HealthTech",
    "Biotechnology Research": "HealthTech",
    "Biotech": "HealthTech",
    "Pharmaceutical Manufacturing": "HealthTech",
    "Retail": "E-commerce",
    "Retail Luxury Goods and Jewelry": "E-commerce",
}

WIKIDATA_MAPPING = {
    "IT service management": "Service Industry",
    "information technology consulting": "Service Industry",
    "financial services": "Fintech",
    "banking": "Fintech",
    "pharmaceutical industry": "HealthTech",
    "biotechnology": "HealthTech",
    "retail": "E-commerce",
    "artificial intelligence": "Artificial Intelligence",
}

VALID_COMPANY_QIDS = {
    "Q4830453",  # business enterprise
    "Q89172",    # public company
    "Q6881511",   # enterprise
    "Q2626503",   # limited company
    "Q161262",    # joint-stock company
    "Q22687",     # multinational corporation
    "Q326339",    # private company limited by shares
    "Q1932158",   # nonprofit organization
    "Q11436",     # company
}

TAXONOMY = [
    ("Service Industry", r'\b(?:it\s*services|technology\s+(?:[\w&]+\s+){0,3}services|information\s*technology\s*services|technology\s*consulting|system\s*integration|managed\s*services|outsourcing|digital\s*transformation)\b'),
    ("Fintech", r'\b(?:fintech|payment|payments|bank|banking|credit|lending|insurance|insurtech|wealth|crypto|blockchain|finance|financial\s+services|neobank|accounting)\b'),
    ("HealthTech", r'\b(?:health|healthtech|biotech|medical|pharma|clinical|healthcare|wellness|genomics)\b'),
    ("E-commerce", r'\b(?:e\s*commerce|ecommerce|marketplace|d2c|retail(?:er)?s?|shopping|q\s*commerce|quick\s*commerce|rapid\s*commerce)\b'),
    ("EdTech", r'\b(?:edtech|education|(?<!machine\s)(?<!deep\s)learning|upskilling|tutor|university|course)\b'),
    ("CleanTech", r'\b(?:cleantech|climate|solar|ev|electric\s*vehicle|battery|renewable|sustainability|carbon)\b'),
    ("Cybersecurity", r'\b(?:security|cybersecurity|infosec|encryption|identity|firewall|compliance)\b'),
    ("Logistics", r'\b(?:logistics|supply\s*chain|fleet|mobility|freight|delivery|warehousing)\b'),
    ("Artificial Intelligence", r'\b(?:ai|artificial\s*intelligence|machine\s*learning|llm|genai|generative\s*ai|nlp|deep\s*learning|computer\s*vision)\b'),
    ("SaaS", r'\b(?:saas|b2b|enterprise|cloud|workflow|api|platform|devtool|software)\b')
]

wikidata_cache = {}

def get_wikidata_industry(company_name):
    """Get company industry from cache or query Wikidata."""
    if not company_name or company_name == "N/A":
        return None
    disable_wiki = os.environ.get("DISABLE_WIKIDATA")
    offline_mode = os.environ.get("OFFLINE_MODE")
    if (disable_wiki is not None and disable_wiki.lower() not in ('', '0', 'false', 'no')) or \
       (offline_mode is not None and offline_mode.lower() not in ('', '0', 'false', 'no')):
        return None
    if company_name in wikidata_cache:
        return wikidata_cache[company_name]
    res = _query_wikidata_industry(company_name)
    wikidata_cache[company_name] = res
    return res

def _query_wikidata_industry(company_name):
    delay_mult = float(os.environ.get("DELAY_MULTIPLIER", 0.0))
    if delay_mult > 0:
        time.sleep(0.5 * delay_mult)
    search_url = "https://www.wikidata.org/w/api.php"
    headers = {
        "User-Agent": "JobVisualizerBot/1.0 (singhujwal@gmail.com) Python-Requests"
    }
    try:
        # 1. Search for entity
        r = requests.get(search_url, params={
            "action": "wbsearchentities", "search": company_name, "language": "en", "format": "json"
        }, headers=headers, timeout=3)
        r.raise_for_status()
        results = r.json().get("search", [])
        if not results:
            return None
        entity_id = results[0]["id"]
        
        # 2. Get claims
        r = requests.get(search_url, params={
            "action": "wbgetentities", "ids": entity_id, "format": "json", "props": "claims"
        }, headers=headers, timeout=3)
        r.raise_for_status()
        claims = r.json().get("entities", {}).get(entity_id, {}).get("claims", {})
        
        # Verify P31 (instance of) matches common company QIDs
        p31_claims = claims.get("P31", [])
        is_company = False
        for claim in p31_claims:
            val_id = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
            if val_id in VALID_COMPANY_QIDS:
                is_company = True
                break
                
        if not is_company:
            print(f"[Wikidata] Entity {entity_id} for '{company_name}' is not verified as a company.")
            return None

        # Get P452 (industry)
        industry_claims = claims.get("P452", [])
        if not industry_claims:
            return None
        industry_id = industry_claims[0].get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
        if not industry_id:
            return None
            
        # 3. Get label of industry
        r = requests.get(search_url, params={
            "action": "wbgetentities", "ids": industry_id, "format": "json", "props": "labels"
        }, headers=headers, timeout=3)
        r.raise_for_status()
        label = r.json().get("entities", {}).get(industry_id, {}).get("labels", {}).get("en", {}).get("value")
        return label
    except Exception as e:
        print(f"[Wikidata] Error looking up '{company_name}': {e}")
        return None

def classify_startup(startup, force=False):
    name = startup.get("name", "")
    curr = str(startup.get("industry") or "").strip()
    valid_sectors = {t[0] for t in TAXONOMY}

    # Skip if already classified and not forcing
    if not force and curr in valid_sectors:
        return curr

    # 1. Try LinkedIn mapping first
    if curr in LINKEDIN_MAPPING:
        return LINKEDIN_MAPPING[curr]

    # 2. Try Wikidata fallback
    wiki_ind = get_wikidata_industry(name)
    if wiki_ind and wiki_ind in WIKIDATA_MAPPING:
        print(f"[Classification] Mapped '{name}' via Wikidata: '{wiki_ind}' -> '{WIKIDATA_MAPPING[wiki_ind]}'")
        return WIKIDATA_MAPPING[wiki_ind]

    # 3. Fallback to keyword search
    text = f"{name} {startup.get('description', '')} {startup.get('website', '')}".lower()
    
    hc = startup.get("head_count")
    try:
        hc_val = int(hc) if hc is not None else 0
    except ValueError:
        hc_val = 0

    if hc_val < 1000:
        jobs = startup.get("job_openings") or []
        for j in jobs:
            if isinstance(j, dict):
                text += f" {j.get('title', '')} {j.get('department', '')}".lower()

    text = re.sub(r'[^a-zA-Z0-9]', ' ', text)
    text = re.sub(r'\s+', ' ', text)

    for sector, pattern in TAXONOMY:
        if re.search(pattern, text, re.IGNORECASE):
            return sector

    return curr if curr in valid_sectors else "SaaS"

def run_classification(db_path, force=False):
    db = DBManager(db_path=db_path)
    with DBManager.file_lock(db_path):
        db.load_db()
        data = db.get_all_startups()
        updated_count = 0
        for s in data:
            old_ind = s.get("industry")
            new_ind = classify_startup(s, force=force)
            if old_ind != new_ind:
                s["industry"] = new_ind
                updated_count += 1
        if updated_count > 0:
            db.save_db()
    print(f"Successfully processed {len(data)} startups. Updated industry classifications for {updated_count} startups.")

def main():
    parser = argparse.ArgumentParser(description="Classify company industries.")
    parser.add_argument("--force", action="store_true", help="Force re-classification of all companies.")
    parser.add_argument("--db-path", help="Path to startups.json database.")
    args = parser.parse_args()

    db_path = args.db_path or os.environ.get("STARTUP_DB_PATH")
    if not db_path:
        db_path = os.path.abspath(os.path.join(PROJECT_ROOT, "backend", "startups.json"))
        
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return
        
    run_classification(db_path, force=args.force)

if __name__ == '__main__':
    main()
