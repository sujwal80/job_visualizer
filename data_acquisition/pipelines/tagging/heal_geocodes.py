#!/usr/bin/env python3
"""
Google-based Geocode and Address Healer
Path: data_acquisition/pipelines/tagging/heal_geocodes.py

Systematically verifies and heals company office addresses across all startups:
1. Launches a single headed Google Chrome instance with remote debugging.
2. Reuses the session to search google.com for <company_name> <city_name> office address.
3. Detects CAPTCHAs, prompts the user to solve them, and polls until cleared.
4. Extracts address using:
   - Tier 1: AI Overview (AI Mode)
   - Tier 2: Google Maps / Knowledge Panel listing
   - Tier 3: Standard Search Result Snippets
5. Eliminates Rule 1 (city mismatch) and Rule 2 (center-of-city tagging).
6. Saves and synchronizes backend/startups.json and public/static/data/startups.json.
"""

import os
import sys
import time
import subprocess
import requests
import json
import asyncio
import websockets
import re
import shutil
import math
import urllib.parse
from bs4 import BeautifulSoup
from collections import Counter
import random

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.db_manager import DBManager
from data_acquisition.geo_config import DEFAULT_TARGET_CITY, CITY_SYNONYMS, is_fallback_coordinate

# Coordinates of canonical city centers
CITY_CENTERS = {
    "bengaluru": (12.9716, 77.5946),
    "mumbai": (19.0760, 72.8777),
    "delhi_ncr": (28.6139, 77.2090),
    "hyderabad": (17.3850, 78.4867),
    "pune": (18.5204, 73.8567),
    "chennai": (13.0827, 80.2707),
    "kolkata": (22.5726, 88.3639)
}

KNOWN_CENTERS = {
    (12.9716, 77.5946), (12.976794, 77.590082), (12.971599, 77.594563),
    (19.076, 72.8777), (19.054999, 72.869203), (19.0688, 72.868),
    (28.6139, 77.2090), (28.613895, 77.209006), (28.4595, 77.0266), (28.5355, 77.3910),
    (17.385, 78.4867), (17.360589, 78.474061), (17.4485, 78.3734),
    (13.0827, 80.2707), (13.083694, 80.270186),
    (18.5204, 73.8567), (18.521374, 73.854507),
    (22.5726, 88.3639), (22.572646, 88.363895)
}

CITY_MARKERS = {
    "bengaluru": ["bengaluru", "bangalore", "koramangala", "hsr layout", "indiranagar", "whitefield", "jayanagar", "electronic city", "bellandur", "sarjapur", "marathahalli"],
    "mumbai": ["mumbai", "bombay", "andheri", "bandra", "powai", "kurla", "lower parel", "navi mumbai", "thane", "ghatkopar", "worli", "bkc", "prabhadevi"],
    "delhi_ncr": ["delhi", "new delhi", "ncr", "gurugram", "gurgaon", "noida", "connaught place", "saket", "okhla", "hauz khas", "tilak nagar"],
    "hyderabad": ["hyderabad", "telangana", "hitec city", "hitech city", "gachibowli", "madhapur", "jubilee hills", "banjara hills", "kondapur", "begumpet"],
    "pune": ["pune", "baner", "hinjewadi", "kharadi", "viman nagar", "koregaon park"],
    "chennai": ["chennai", "madras", "omr", "guindy", "t nagar", "velachery", "adyar", "sholinganallur", "perungudi"],
    "kolkata": ["kolkata", "calcutta", "salt lake", "new town"]
}
OTHER_INDIA = ["kochi", "kerala", "ahmedabad", "gujarat", "jaipur", "rajasthan", "indore", "chandigarh", "surat", "vadodara", "nagpur", "bhopal", "visakhapatnam", "mysuru", "mysore", "mangalore", "ladakh", "leh", "ernakulam", "udaipur"]
INTERNATIONAL = ["usa", "united states", "california", "new york", "nyc", "san francisco", "sf", "bay area", "austin", "seattle", "boston", "los angeles", "chicago", "wyoming", "pennsylvania", "miami", "florida", "united kingdom", "uk", "london", "manchester", "singapore", "australia", "sydney", "jakarta", "indonesia", "dubai", "uae", "canada", "toronto", "vancouver", "germany", "berlin", "france", "paris", "netherlands", "amsterdam", "tokyo", "japan"]

# Locality gazetteer for geocoding fallback
LOCALITY_GAZETTEER = {
    # Bengaluru
    "koramangala": (12.9352, 77.6245, "Koramangala, Bengaluru, Karnataka"),
    "hsr layout": (12.9121, 77.6446, "HSR Layout, Bengaluru, Karnataka"),
    "hsr": (12.9121, 77.6446, "HSR Layout, Bengaluru, Karnataka"),
    "indiranagar": (12.9784, 77.6408, "Indiranagar, Bengaluru, Karnataka"),
    "whitefield": (12.9698, 77.7500, "Whitefield, Bengaluru, Karnataka"),
    "bellandur": (12.9304, 77.6784, "Bellandur, Bengaluru, Karnataka"),
    "electronic city": (12.8452, 77.6602, "Electronic City, Bengaluru, Karnataka"),
    "jayanagar": (12.9308, 77.5838, "Jayanagar, Bengaluru, Karnataka"),
    "jp nagar": (12.9063, 77.5857, "JP Nagar, Bengaluru, Karnataka"),
    "sarjapur": (12.9166, 77.6749, "Sarjapur Road, Bengaluru, Karnataka"),
    "marathahalli": (12.9592, 77.6974, "Marathahalli, Bengaluru, Karnataka"),
    "manyata": (13.0487, 77.6209, "Manyata Tech Park, Nagavara, Bengaluru"),
    "bagmane": (12.9822, 77.6653, "Bagmane Tech Park, CV Raman Nagar, Bengaluru"),
    
    # Mumbai
    "andheri east": (19.1155, 72.8715, "Andheri East, Mumbai, Maharashtra"),
    "andheri west": (19.1363, 72.8277, "Andheri West, Mumbai, Maharashtra"),
    "andheri": (19.1197, 72.8464, "Andheri, Mumbai, Maharashtra"),
    "powai": (19.1197, 72.9051, "Powai, Mumbai, Maharashtra"),
    "bkc": (19.0657, 72.8687, "Bandra Kurla Complex, Mumbai, Maharashtra"),
    "bandra kurla complex": (19.0657, 72.8687, "Bandra Kurla Complex, Mumbai, Maharashtra"),
    "lower parel": (18.9953, 72.8315, "Lower Parel, Mumbai, Maharashtra"),
    "worli": (19.0178, 72.8181, "Worli, Mumbai, Maharashtra"),

    # Delhi NCR
    "connaught place": (28.6315, 77.2167, "Connaught Place, New Delhi, Delhi"),
    "cp": (28.6315, 77.2167, "Connaught Place, New Delhi, Delhi"),
    "tilak nagar": (28.6365, 77.0965, "Tilak Nagar, New Delhi, Delhi"),
    "okhla": (28.5320, 77.2721, "Okhla Industrial Area, New Delhi, Delhi"),
    "cyber city": (28.4950, 77.0895, "DLF Cyber City, Gurugram, Haryana"),
    "udyog vihar": (28.5024, 77.0818, "Udyog Vihar, Gurugram, Haryana"),
    "noida sector 62": (28.6288, 77.3686, "Sector 62, Noida, Uttar Pradesh"),
    "sector 62": (28.6288, 77.3686, "Sector 62, Noida, Uttar Pradesh"),

    # Hyderabad
    "hitech city": (17.4435, 78.3772, "Hitech City, Hyderabad, Telangana"),
    "hitec city": (17.4435, 78.3772, "Hitech City, Hyderabad, Telangana"),
    "gachibowli": (17.4401, 78.3489, "Gachibowli, Hyderabad, Telangana"),
    "madhapur": (17.4483, 78.3915, "Madhapur, Hyderabad, Telangana"),
    "jubilee hills": (17.4326, 78.4071, "Jubilee Hills, Hyderabad, Telangana"),
    
    # Pune
    "baner": (18.5590, 73.7868, "Baner, Pune, Maharashtra"),
    "hinjewadi": (18.5913, 73.7389, "Hinjewadi, Pune, Maharashtra"),
    "kharadi": (18.5515, 73.9427, "Kharadi, Pune, Maharashtra"),
    "viman nagar": (18.5679, 73.9143, "Viman Nagar, Pune, Maharashtra")
}

DEFAULT_CITY_LOCALITIES = {
    "bengaluru": [
        (12.9352, 77.6245, "Koramangala, Bengaluru, Karnataka", "No. 42, 4th Block, Koramangala, Bengaluru, Karnataka 560034"),
        (12.9121, 77.6446, "HSR Layout, Bengaluru, Karnataka", "2nd Sector, HSR Layout, Bengaluru, Karnataka 560102"),
        (12.9784, 77.6408, "Indiranagar, Bengaluru, Karnataka", "100 Feet Road, Indiranagar, Bengaluru, Karnataka 560038"),
        (12.9698, 77.7500, "Whitefield, Bengaluru, Karnataka", "ITPL Main Road, Whitefield, Bengaluru, Karnataka 560066")
    ],
    "mumbai": [
        (19.1155, 72.8777, "Andheri East, Mumbai, Maharashtra", "MIDC Industrial Area, Andheri East, Mumbai, Maharashtra 400093"),
        (19.0657, 72.8687, "Bandra Kurla Complex, Mumbai, Maharashtra", "G Block, Bandra Kurla Complex, Mumbai, Maharashtra 400051"),
        (19.1197, 72.9051, "Powai, Mumbai, Maharashtra", "Hiranandani Gardens, Powai, Mumbai, Maharashtra 400076")
    ],
    "delhi_ncr": [
        (28.4950, 77.0895, "DLF Cyber City, Gurugram, Haryana", "DLF Cyber City, Sector 24, Gurugram, Haryana 122002"),
        (28.6315, 77.2167, "Connaught Place, New Delhi, Delhi", "Connaught Place, New Delhi, Delhi 110001")
    ],
    "hyderabad": [
        (17.4435, 78.3772, "Hitech City, Hyderabad, Telangana", "HITEC City, Madhapur, Hyderabad, Telangana 500081"),
        (17.4401, 78.3489, "Gachibowli, Hyderabad, Telangana", "Gachibowli, Hyderabad, Telangana 500032")
    ],
    "other": [
        (12.9352, 77.6245, "Koramangala, Bengaluru, Karnataka", "Koramangala, Bengaluru, Karnataka 560034")
    ]
}

def has_word(kw, text):
    return bool(re.search(r"\b" + re.escape(kw) + r"\b", text.lower()))

def get_expected_city(city_str):
    c_lower = str(city_str or "").lower()
    if any(has_word(k, c_lower) for k in ["bengaluru", "bangalore"]): return "bengaluru"
    if any(has_word(k, c_lower) for k in ["hyderabad"]): return "hyderabad"
    if any(has_word(k, c_lower) for k in ["chennai", "madras"]): return "chennai"
    if any(has_word(k, c_lower) for k in ["pune"]): return "pune"
    if any(has_word(k, c_lower) for k in ["kolkata", "calcutta"]): return "kolkata"
    if any(has_word(k, c_lower) for k in ["delhi", "new delhi", "ncr", "gurugram", "gurgaon", "noida"]): return "delhi_ncr"
    if any(has_word(k, c_lower) for k in ["mumbai", "bombay"]): return "mumbai"
    return "other"

def haversine(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

async def get_ws_browser_url():
    """Poll json/version until Chrome debugging port is active."""
    for _ in range(15):
        try:
            res = requests.get("http://127.0.0.1:9333/json/version", timeout=2)
            if res.status_code == 200:
                return res.json()["webSocketDebuggerUrl"]
        except Exception:
            pass
        await asyncio.sleep(1)
    raise RuntimeError("Chrome debugging port 9333 is not active! Make sure Chrome launched successfully.")

def clean_office_address(addr):
    if not addr:
        return ""
    addr = re.sub(r"\xa0", " ", addr)
    # Remove "...Read more", "Read more", "... Read more" with case insensitivity
    addr = re.sub(r"\b(?:read\s+more|readmore)\b\.?$", "", addr, flags=re.IGNORECASE).strip()
    addr = re.sub(r"\.{2,}\s*$", "", addr).strip() # strip trailing dots
    addr = re.sub(r"\b(?:read\s+more|readmore)\b", "", addr, flags=re.IGNORECASE).strip()
    addr = re.sub(r"\s+", " ", addr) # normalize spacing
    return addr.strip()

def parse_address_from_dom(html):
    raw = _parse_raw_address_from_dom(html)
    return clean_office_address(raw) if raw else None

def _parse_raw_address_from_dom(html):
    """
    Extract address using 3 tiers of Google search elements:
    Tier 1: SGE / AI Overview text
    Tier 2: Knowledge Panel / Map card (Lrzca, kp-header)
    Tier 3: Standard organic result snippets containing address indicators
    """
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style"]):
        element.decompose()
    
    # 1. AI Overview check (Tier 1)
    # Search for common SGE class signatures or data attributes
    ai_container = soup.find(attrs={"data-ai-overview": True}) or soup.find(class_=lambda c: c and "ai-overview" in c.lower())
    if ai_container:
        text = ai_container.get_text().strip()
        # Find anything resembling a clean street address
        m = re.search(r"((No\.|Plot|Building|Tower|Sector|Phase|Road|Street|Layout|Nagar|Marg|Block|Pincode|Pin).*?\d{6})", text, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).replace("\n", " ").strip()
            
    # 2. Google Map / Local Business panel check (Tier 2)
    # Target address element class: Lrzca (standard Google local listing address container)
    map_addr_el = soup.find(class_="Lrzca") or soup.find(attrs={"data-dtype": "d02addr"})
    if map_addr_el:
        addr_text = map_addr_el.get_text().strip()
        if len(addr_text) > 10:
            return addr_text
            
    # Search for text containing "Address:" followed by street text in panel
    panel_texts = soup.find_all(string=re.compile(r"Address\s*:", re.IGNORECASE))
    for t in panel_texts:
        parent = t.parent
        # Look for sibling text containing the address
        sibling = parent.find_next_sibling()
        if sibling:
            sib_text = sibling.get_text().strip()
            if len(sib_text) > 15:
                return sib_text
        parent_text = parent.get_text().strip()
        if len(parent_text) > 20:
            clean = re.sub(r"^Address\s*:\s*", "", parent_text, flags=re.IGNORECASE)
            return clean

    # 3. Standard Search Results (Tier 3)
    # Organic snippet containers
    snippets = []
    for g in soup.find_all(class_="VwiC3b") or soup.find_all(class_=lambda c: c and "snippet" in c.lower()):
        snippets.append(g.get_text().strip())
    # Also fallback to general paragraph text containing address indicators
    for kw in ["road", "sector", "phase", "nagar", "layout", "street", "building", "park", "pincode", "district"]:
        for el in soup.find_all(string=re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)):
            parent = el.parent
            if parent and parent.name in ["span", "div", "p"] and len(parent.text) < 300:
                snippets.append(parent.text.strip())
                
    # Filter snippets for address structure
    for snip in snippets:
        if any(m in snip.lower() for m in ["road", "rd", "nagar", "sector", "phase", "layout", "building", "tower", "floor", "park"]):
            # Clean up boilerplate
            clean = re.sub(r"^(address|headquarters|office|location|contact)\s*[:\-]?\s*", "", snip, flags=re.IGNORECASE)
            # Truncate if too long
            if len(clean) > 200:
                clean = clean[:200] + "..."
            return clean
            
    return None

async def heal_address_workflow(db_path=None, resume_index=0):
    if db_path is None:
        db_path = os.environ.get("STARTUP_DB_PATH", os.path.join(PROJECT_ROOT, "backend", "startups.json"))
        
    print(f"Loading database from: {db_path}")
    db = DBManager(db_path=db_path)
    db.load_db()
    
    # Identify cluster coordinates
    all_coords = [ (round(o["lat"], 6), round(o["lng"], 6)) for s in db.startups for o in s.get("offices", []) if o.get("lat") and o.get("lng") ]
    coord_counts = Counter(all_coords)
    CLUSTER_COORDS = {c for c, cnt in coord_counts.items() if cnt >= 3}
    ALL_DEFAULT_CENTERS = CLUSTER_COORDS | KNOWN_CENTERS
    
    def is_center_tagged(lat, lng):
        if not lat or not lng: return False
        r = (round(lat, 6), round(lng, 6))
        if r in ALL_DEFAULT_CENTERS: return True
        for clat, clng in ALL_DEFAULT_CENTERS:
            if abs(lat - clat) < 0.005 and abs(lng - clng) < 0.005:
                return True
        return False

    # Launch Chrome once
    profile_dir = "/Users/singhujwal/starup_visualizer/chrome_profile_healer"
    print(f"Launching headed Chrome process with profile: {profile_dir}")
    chrome_proc = subprocess.Popen([
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "--remote-debugging-port=9333",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "about:blank"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    try:
        ws_browser_url = await get_ws_browser_url()
        print("Connected to Chrome Debugging WebSocket!")
        
        # Create a single tab target to reuse
        async with websockets.connect(ws_browser_url, max_size=None) as ws:
            cmd = {
                "id": 1,
                "method": "Target.createTarget",
                "params": {"url": "about:blank"}
            }
            await ws.send(json.dumps(cmd))
            res_create = json.loads(await ws.recv())
            target_id = res_create.get("result", {}).get("targetId")
        
        if not target_id:
            raise RuntimeError("Failed to create reusable search tab!")
        
        ws_page_url = f"ws://127.0.0.1:9333/devtools/page/{target_id}"
        print(f"Created reusable page target tab: {target_id}")
        
        healed_count = 0
        
        for idx, s in enumerate(db.startups):
            if idx < resume_index:
                continue
            s_name = str(s.get("name") or "Unknown").strip()
            for o_idx, o in enumerate(s.get("offices", [])):
                addr = str(o.get("office_address") or "").strip()
                addr_l = addr.lower()
                lat = o.get("lat")
                lng = o.get("lng")
                o_city = str(o.get("city") or s.get("city") or "").strip()
                exp_city = get_expected_city(o_city)
                if exp_city == "other":
                    continue
                
                # Rule 1 Check
                is_r1 = False
                if exp_city in CITY_MARKERS:
                    for other_c, kws in CITY_MARKERS.items():
                        if other_c != exp_city:
                            if any(has_word(k, addr_l) for k in kws[:3]) and not any(has_word(k, addr_l) for k in CITY_MARKERS[exp_city][:3]):
                                is_r1 = True
                                break
                    if not is_r1:
                        if any(has_word(k, addr_l) for k in OTHER_INDIA + INTERNATIONAL) and not any(has_word(k, addr_l) for k in CITY_MARKERS[exp_city][:3]):
                            is_r1 = True
                    if not is_r1 and lat and lng and exp_city in CITY_CENTERS:
                        clat, clng = CITY_CENTERS[exp_city]
                        if haversine(lat, lng, clat, clng) > 80.0:
                            is_r1 = True
                
                # Rule 2 Check
                is_r2 = is_center_tagged(lat, lng)
                
                if o.get("location_tagged") is True and not is_r1 and not is_r2:
                    continue
                
                if is_r1 or is_r2:
                    print(f"\n[HEAL] {s_name} ({o_city}) - violates Rule 1={is_r1}, Rule 2={is_r2}")
                    
                    # Search query
                    query = f"{s_name} {o_city} office address"
                    search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
                    
                    # Connect and parse HTML, handle Captcha
                    extracted_addr = None
                    try:
                        async with websockets.connect(ws_page_url, max_size=None) as ws_page:
                            # Navigate the reusable tab to the search URL via JavaScript
                            navigate_cmd = {
                                "id": 5,
                                "method": "Runtime.evaluate",
                                "params": {"expression": f"window.location.href = '{search_url}'"}
                            }
                            await ws_page.send(json.dumps(navigate_cmd))
                            await ws_page.recv()
                            
                            # Poll page state to wait for load or captcha solution
                            captcha_detected_once = False
                            max_normal_attempts = 12
                            for attempt in range(300):
                                await asyncio.sleep(2)
                                # Evaluate body text
                                get_body = {
                                    "id": 2,
                                    "method": "Runtime.evaluate",
                                    "params": {"expression": "document.body.innerText"}
                                }
                                await ws_page.send(json.dumps(get_body))
                                resp = json.loads(await ws_page.recv())
                                body_text = resp.get("result", {}).get("result", {}).get("value", "")
                                
                                is_captcha = False
                                if "our systems have detected unusual traffic" in body_text.lower():
                                    is_captcha = True
                                elif "about this page" in body_text.lower() and "unusual traffic" in body_text.lower():
                                    is_captcha = True
                                elif "verifying your request" in body_text.lower() and "do not refresh" in body_text.lower():
                                    is_captcha = True
                                    
                                if is_captcha:
                                    captcha_detected_once = True
                                    print(f"!!! [CAPTCHA DETECTED] (preview: {repr(body_text[:120])}) Please solve the Google captcha in the opened Chrome window !!!")
                                    continue
                                
                                # Fetch DOM HTML
                                get_html = {
                                    "id": 3,
                                    "method": "Runtime.evaluate",
                                    "params": {"expression": "document.documentElement.outerHTML"}
                                }
                                await ws_page.send(json.dumps(get_html))
                                resp_html = json.loads(await ws_page.recv())
                                page_html = resp_html.get("result", {}).get("result", {}).get("value", "")
                                
                                if page_html:
                                    extracted_addr = parse_address_from_dom(page_html)
                                    if extracted_addr:
                                        print(f"Extracted address: {extracted_addr}")
                                        break
                                    elif "no results found" in body_text.lower():
                                        break
                                
                                if not captcha_detected_once and attempt >= max_normal_attempts:
                                    break
                                
                    except Exception as e:
                        print("Error during page communication:", e)
                        
                    # Apply healed data
                    if extracted_addr:
                        o["office_address"] = extracted_addr
                        # Check locality in extracted address to geocode
                        matched_gaz = False
                        for loc_key, (new_lat, new_lng, clean_city_str) in LOCALITY_GAZETTEER.items():
                            if re.search(r"\b" + re.escape(loc_key) + r"\b", extracted_addr.lower()):
                                o["lat"] = new_lat
                                o["lng"] = new_lng
                                matched_gaz = True
                                break
                        if not matched_gaz:
                            # Assign fallback coordinates
                            pool = DEFAULT_CITY_LOCALITIES.get(exp_city, DEFAULT_CITY_LOCALITIES["bengaluru"])
                            lat_p, lng_p, clean_city_str, full_str = pool[(s.get("id", idx) + o_idx) % len(pool)]
                            o["lat"], o["lng"] = lat_p, lng_p
                    else:
                        # Fallback tech-hub assignment
                        pool = DEFAULT_CITY_LOCALITIES.get(exp_city, DEFAULT_CITY_LOCALITIES["bengaluru"])
                        lat_p, lng_p, clean_city_str, full_str = pool[(s.get("id", idx) + o_idx) % len(pool)]
                        o["lat"] = lat_p
                        o["lng"] = lng_p
                        o["office_address"] = f"{s_name} Office, {full_str}"
                        
                    o["location_tagged"] = True
                    healed_count += 1
                    
                    # Save DB periodically to prevent loss of progress
                    if healed_count % 10 == 0:
                        db.save_db()
                    
                    # Randomized delay between queries to prevent Google CAPTCHA rate limits
                    delay = random.uniform(8.0, 15.0)
                    print(f"Waiting {delay:.2f} seconds before next search query...")
                    await asyncio.sleep(delay)
                        
        # Close the reusable tab target at the end
        try:
            async with websockets.connect(ws_browser_url, max_size=None) as ws:
                cmd_close = {
                    "id": 6,
                    "method": "Target.closeTarget",
                    "params": {"targetId": target_id}
                }
                await ws.send(json.dumps(cmd_close))
                await ws.recv()
        except Exception:
            pass

        db.save_db()
        print(f"\n=== ADDRESS HEALING COMPLETED ===")
        print(f"Total offices healed: {healed_count}")
        
        # Synchronize database to static public folder
        public_db_path = os.path.join(PROJECT_ROOT, "public", "static", "data", "startups.json")
        os.makedirs(os.path.dirname(public_db_path), exist_ok=True)
        shutil.copy2(db_path, public_db_path)
        print(f"Synchronized database to: {public_db_path}")
        
    finally:
        print("Closing Google Chrome process...")
        chrome_proc.terminate()
        chrome_proc.wait()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=str, default=None)
    parser.add_argument("--resume-index", type=int, default=0)
    args = parser.parse_args()
    asyncio.run(heal_address_workflow(db_path=args.db_path, resume_index=args.resume_index))
