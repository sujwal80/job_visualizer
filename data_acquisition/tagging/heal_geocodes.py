import os
import sys
import time
import requests
from bs4 import BeautifulSoup
import urllib.parse
import re

# Add project root and data_acquisition directory to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
DATA_ACQ_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if DATA_ACQ_DIR not in sys.path:
    sys.path.insert(0, DATA_ACQ_DIR)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from db_manager import DBManager
try:
    from geo_config import DEFAULT_TARGET_CITY, is_fallback_coordinate, CITY_SYNONYMS
    from tagging.remote_office_classifier import check_remote_office_status
except ImportError:
    from data_acquisition.geo_config import DEFAULT_TARGET_CITY, is_fallback_coordinate, CITY_SYNONYMS
    from data_acquisition.tagging.remote_office_classifier import check_remote_office_status

def clean_snippet_to_address(snippet, target_city=None):
    if target_city is None:
        target_city = DEFAULT_TARGET_CITY
    city_esc = re.escape(str(target_city))
    # Strip common prefixes from the start of the snippet
    snippet = re.sub(r'^(get|find|' + city_esc + r'|bangalore|bengaluru|office|headquarters|contact|address)?\s*office\s+(address|location|space)?\s*[:\-]?\s*', '', snippet, flags=re.IGNORECASE)
    snippet = re.sub(r'^\b(headquartered in|headquarters at|located in|located at)\b\s*', '', snippet, flags=re.IGNORECASE)
    
    parts = [p.strip() for p in snippet.split(',')]
    clean_parts = []
    
    noise_keywords = [
        "headquartered", "headquarter", "locations", "office location", "jobs", "reviews", 
        "salaries", "employees", "workspace", "nestled", "vibrant", "more than just", 
        "overview", "campus", "major", "posted", "anonymously", "learn about", "ratings"
    ]
    
    for p in parts:
        p_lower = p.lower()
        if any(nk in p_lower for nk in noise_keywords):
            continue
        if p_lower in ["india", "in", "us", "united states", "uk"]:
            continue
        # Strip trailing search noise
        p_clean = re.sub(r'\band has\s+\d+.*$', '', p, flags=re.IGNORECASE).strip()
        p_clean = re.sub(r'\bclick here.*$', '', p_clean, flags=re.IGNORECASE).strip()
        if p_clean:
            clean_parts.append(p_clean)
            
    if not clean_parts:
        return None
        
    address = ", ".join(clean_parts)
    # Ensure target city is at the end if not present
    target_lower = target_city.lower()
    synonyms = CITY_SYNONYMS.get(target_lower, [target_lower])
    if not any(k in address.lower() for k in synonyms + [target_lower]):
        address += f", {target_city}"
        
    return address

def get_address_from_ddg(company_name, target_city=None):
    if target_city is None:
        target_city = DEFAULT_TARGET_CITY
    target_lower = target_city.lower()
    synonyms = CITY_SYNONYMS.get(target_lower, [target_lower])
    query = f"{company_name} {target_city} office address"
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        delay_mult = float(os.environ.get("DELAY_MULTIPLIER", 0.0))
        if delay_mult > 0:
            time.sleep(1.5 * delay_mult)
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            results = soup.find_all('div', class_='result')
            for r in results[:3]:
                snippet_el = r.find('a', class_='result__snippet')
                if snippet_el:
                    snippet = snippet_el.text.strip()
                    snippet_lower = snippet.lower()
                    has_city = any(k in snippet_lower for k in synonyms + [target_lower])
                    has_address_markers = any(m in snippet_lower for m in [
                        "hsr", "koramangala", "indiranagar", "whitefield", "road", "rd",
                        "layout", "sector", "phase", "nagar", "building", "floor", "block",
                        "pincode", "pin", "560", "400", "110", "500", "411", "600", "201", "122",
                        "heights", "estates", "tower", "sarakki", "abhaya", "street", "st",
                        "marg", "vihar", "enclave", "park", "hub", "ave", "avenue", "blvd",
                        "boulevard", "suite", "ste", "drive", "dr", "way", "lane", "ln",
                        "place", "pl", "square", "sq", "court", "ct", "plaza", "center"
                    ])
                    
                    if has_city and has_address_markers:
                        cleaned = clean_snippet_to_address(snippet, target_city=target_city)
                        if cleaned:
                            return cleaned
    except Exception as e:
        print(f"  [DDG Search] Error searching DDG for '{company_name}': {e}")
    return None

def heal_geocodes(target_city=None):
    if target_city is None:
        target_city = DEFAULT_TARGET_CITY
    db_path = os.environ.get("STARTUP_DB_PATH", os.path.join(PROJECT_ROOT, "backend", "startups.json"))
    
    print("=== STARTING OFFLINE GEOLOCATION HEALER WITH DDG FALLBACK ===")
    print(f"Loading database from: {db_path} (Target City: {target_city})")
    
    db = DBManager(db_path)
    
    heal_count = 0
    success_count = 0
    
    # We check for our fallback coordinates
    def is_fallback(lat, lng):
        return is_fallback_coordinate(lat, lng)
        
    startups_to_heal = [s for s in db.startups if is_fallback(s.get("lat"), s.get("lng"))]
    print(f"Found {len(startups_to_heal)} startups at fallback coordinates that need healing.")
    
    for idx, s in enumerate(startups_to_heal):
        name = s.get("name")
        address = s.get("city") or target_city
        
        print(f"\n[Healer {idx+1}/{len(startups_to_heal)}] Attempting to heal '{name}'...")
        print(f"  Current Address/Locality in DB: '{address}'")
        
        heal_count += 1
        
        # Tier 1: Try to geocode using current database address
        new_lat, new_lng = db.geocode_address(address, name, target_city=target_city)
        
        # Tier 2: If Tier 1 failed to resolve (still at fallback), scrape DDG snippet
        if is_fallback(new_lat, new_lng):
            print(f"  Tier 1 geocoding failed. Searching DuckDuckGo for office address...")
            ddg_address = get_address_from_ddg(name, target_city=target_city)
            if ddg_address:
                print(f"  Extracted DDG Address: '{ddg_address}'")
                new_lat, new_lng = db.geocode_address(ddg_address, name, target_city=target_city)
                
        # If it resolved successfully to a non-fallback coordinate
        if not is_fallback(new_lat, new_lng):
            print(f"  [SUCCESS] Resolved '{name}' -> ({new_lat}, {new_lng})")
            
            with db.file_lock(db.db_path):
                db.load_db()
                record = next((x for x in db.startups if x.get("id") == s.get("id")), None)
                if record and is_fallback(record.get("lat"), record.get("lng")):
                    record["lat"] = new_lat
                    record["lng"] = new_lng
                    
                    # Save the resolved address back to the city field (truncated if too long)
                    resolved_addr = ddg_address if 'ddg_address' in locals() and ddg_address else address
                    city_label = resolved_addr
                    if len(city_label) > 60:
                        city_label = city_label.split(',')[0] + f", {target_city}"
                    record["city"] = city_label
                    check_remote_office_status(record, target_city=target_city)
                    record["location_tagged"] = True
                    
                    success_count += 1
                    db.save_db()
        else:
            print(f"  [FAILED] Could not resolve '{name}' to specific coordinates.")
            
        # Clean local variables for next iteration
        ddg_address = None
            
    print("\n=== OFFLINE GEOLOCATION HEALING COMPLETED ===")
    print(f"Processed: {heal_count}")
    print(f"Successfully Healed: {success_count}")
    print(f"Failed / Left at Center: {heal_count - success_count}")

if __name__ == "__main__":
    args = sys.argv[1:]
    target_city = DEFAULT_TARGET_CITY
    if "--city" in args:
        idx = args.index("--city")
        if idx + 1 < len(args):
            target_city = args[idx + 1]
    heal_geocodes(target_city=target_city)
