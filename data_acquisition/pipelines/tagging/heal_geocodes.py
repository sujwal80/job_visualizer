#!/usr/bin/env python3
"""
Google Chrome DOM + ArcGIS Precision Geocode Healer
Path: data_acquisition/pipelines/tagging/heal_geocodes.py

IMPORTANT RULES FOR THIS SCRIPT:
1. NEVER modify, alter, or overwrite `office_address` in the database under ANY circumstances. The address text is finalized and immutable.
2. Paste the full `office_address` directly into the Google Chrome search bar.
3. Extract real latitude and longitude numbers exclusively from:
   - Tier 1: Embedded Google Maps URLs/links in the Chrome DOM (@lat,lng or ll=lat,lng).
   - Tier 2: Free ArcGIS World Geocoding API on the exact full address string.
   - Tier 3: Known Tech-Park and Locality Gazetteer coordinates.
4. ONLY update `lat` and `lng` for offices violating Rule 1 (outside city >80km) or Rule 2 (center of city).
5. Synchronize backend/startups.json and public/static/data/startups.json after processing.
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
import random

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.db_manager import DBManager
from data_acquisition.geo_config import DEFAULT_TARGET_CITY, CITY_SYNONYMS

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
    (12.9716, 77.5946), (12.976794, 77.590082), (12.971599, 77.594563), (12.9767936, 77.590082),
    (19.076, 72.8777), (19.054999, 72.869203), (19.0688, 72.868), (19.0759837, 72.8776559),
    (28.6139, 77.2090), (28.613895, 77.209006), (28.4595, 77.0266), (28.5355, 77.3910), (28.6138954, 77.2090057),
    (17.385, 78.4867), (17.360589, 78.474061), (17.4485, 78.3734), (17.360589, 78.4740613), (17.385044, 78.486671),
    (13.0827, 80.2707), (13.083694, 80.270186), (13.0836939, 80.270186),
    (18.5204, 73.8567), (18.521374, 73.854507), (18.5213738, 73.854507),
    (22.5726, 88.3639), (22.572646, 88.363895), (22.5726459, 88.363895)
}

CITY_MARKERS = {
    "bengaluru": ["bengaluru", "bangalore", "koramangala", "hsr layout", "indiranagar", "whitefield", "jayanagar", "electronic city", "bellandur", "sarjapur", "marathahalli"],
    "mumbai": ["mumbai", "bombay", "andheri", "bandra", "powai", "kurla", "lower parel", "navi mumbai", "thane", "ghatkopar", "worli", "bkc", "prabhadevi"],
    "delhi_ncr": ["delhi", "new delhi", "ncr", "gurugram", "gurgaon", "noida", "connaught place", "saket", "okhla", "hauz khas", "tilak nagar"],
    "hyderabad": ["hyderabad", "telangana", "hitec city", "hitech city", "gachibowli", "madhapur", "jubilee hills", "banjara hills", "kondapur", "begumpet"],
    "pune": ["pune", "baner", "hinjewadi", "kharadi", "viman nagar", "koregaon park"],
    "chennai": ["chennai", "madras", "omr", "guindy", "t nagar", "velachery", "adyar", "sholinganallur", "perungudi"],
    "kolkata": ["kolkata", "calcutta", "salt lake", "new town", "rajarhat", "sector v"]
}

OTHER_INDIA = ["kochi", "kerala", "ahmedabad", "gujarat", "jaipur", "rajasthan", "indore", "chandigarh", "surat", "vadodara", "nagpur", "bhopal", "visakhapatnam", "mysuru", "mysore", "mangalore", "ladakh", "leh", "ernakulam", "udaipur"]
INTERNATIONAL = ["usa", "united states", "california", "new york", "nyc", "san francisco", "sf", "bay area", "austin", "seattle", "boston", "los angeles", "chicago", "wyoming", "pennsylvania", "miami", "florida", "united kingdom", "uk", "london", "manchester", "singapore", "australia", "sydney", "jakarta", "indonesia", "dubai", "uae", "canada", "toronto", "vancouver", "germany", "berlin", "france", "paris", "netherlands", "amsterdam", "tokyo", "japan"]

LOCALITY_GAZETTEER = {
    # Bengaluru
    "koramangala": (12.9352, 77.6245), "hsr layout": (12.9121, 77.6446), "indiranagar": (12.9784, 77.6408),
    "whitefield": (12.9698, 77.7500), "bellandur": (12.9304, 77.6784), "electronic city": (12.8452, 77.6602),
    "jayanagar": (12.9308, 77.5838), "jp nagar": (12.9063, 77.5857), "sarjapur": (12.9166, 77.6749),
    "marathahalli": (12.9592, 77.6974), "manyata": (13.0487, 77.6209), "bagmane": (12.9822, 77.6653),
    "rmz ecoworld": (12.9220, 77.6833), "embassy golf links": (12.9472, 77.6394),
    
    # Mumbai
    "andheri east": (19.1155, 72.8715), "andheri west": (19.1363, 72.8277), "andheri": (19.1197, 72.8464),
    "powai": (19.1197, 72.9051), "bkc": (19.0657, 72.8687), "bandra kurla complex": (19.0657, 72.8687),
    "lower parel": (18.9953, 72.8315), "worli": (19.0178, 72.8181), "ghatkopar": (19.0865, 72.9090),
    "vikhroli": (19.1102, 72.9261), "navi mumbai": (19.0330, 73.0297), "thane": (19.2183, 72.9781),

    # Delhi NCR
    "connaught place": (28.6315, 77.2167), "cp": (28.6315, 77.2167), "tilak nagar": (28.6365, 77.0965),
    "okhla": (28.5320, 77.2721), "cyber city": (28.4950, 77.0895), "udyog vihar": (28.5024, 77.0818),
    "noida sector 62": (28.6288, 77.3686), "sector 62": (28.6288, 77.3686),

    # Hyderabad
    "hitech city": (17.4435, 78.3772), "hitec city": (17.4435, 78.3772), "gachibowli": (17.4401, 78.3489),
    "madhapur": (17.4483, 78.3915), "jubilee hills": (17.4326, 78.4071), "financial district": (17.4262, 78.3389),
    "kondapur": (17.4682, 78.3619),
    
    # Pune
    "baner": (18.5590, 73.7868), "hinjewadi": (18.5913, 73.7389), "kharadi": (18.5515, 73.9427),
    "viman nagar": (18.5679, 73.9143), "koregaon park": (18.5362, 73.8940),
    
    # Chennai
    "omr": (12.9229, 80.2319), "guindy": (13.0067, 80.2206), "t nagar": (13.0418, 80.2341),
    "adyar": (13.0012, 80.2565), "velachery": (12.9815, 80.2180),
    
    # Kolkata
    "salt lake": (22.5867, 88.4172), "sector v": (22.5786, 88.4357), "new town": (22.5958, 88.4795),
    "rajarhat": (22.6200, 88.5100)
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
    for _ in range(15):
        try:
            res = requests.get("http://127.0.0.1:9333/json/version", timeout=2)
            if res.status_code == 200:
                return res.json()["webSocketDebuggerUrl"]
        except Exception:
            pass
        await asyncio.sleep(1)
    raise RuntimeError("Chrome debugging port 9333 is not active! Make sure Chrome launched successfully.")

def parse_coords_from_dom(html):
    """Extract GPS coordinates directly from Google Maps preview links inside the DOM."""
    m = re.search(r'[@|ll=]([0-9]{1,2}\.[0-9]{4,}),([0-9]{1,3}\.[0-9]{4,})', html)
    if m:
        try:
            lat, lng = float(m.group(1)), float(m.group(2))
            if 6.0 <= lat <= 37.0 and 68.0 <= lng <= 98.0:
                return lat, lng
        except Exception:
            pass
    return None, None

def geocode_arcgis(address):
    """Fallback to free ArcGIS World Geocoding API on the exact full address string."""
    if not address or len(address) < 5:
        return None, None
    url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
    params = {"singleLine": address, "f": "json", "maxLocations": 1, "outFields": "Score"}
    try:
        r = requests.get(url, params=params, timeout=6).json()
        candidates = r.get("candidates", [])
        if candidates and candidates[0].get("score", 0) >= 70:
            loc = candidates[0]["location"]
            lat, lng = loc["y"], loc["x"]
            if 6.0 <= lat <= 37.0 and 68.0 <= lng <= 98.0:
                return round(lat, 7), round(lng, 7)
    except Exception:
        pass
    return None, None

async def heal_address_workflow(db_path=None, resume_index=0):
    if db_path is None:
        db_path = os.environ.get("STARTUP_DB_PATH", os.path.join(PROJECT_ROOT, "backend", "startups.json"))
        
    print(f"Loading database from: {db_path}")
    db = DBManager(db_path=db_path)
    db.load_db()
    
    ALL_DEFAULT_CENTERS = KNOWN_CENTERS
    
    def is_center_tagged(lat, lng, exp_city):
        if not lat or not lng: return False
        r1 = (round(lat, 6), round(lng, 6))
        r2 = (round(lat, 4), round(lng, 4))
        if r1 in ALL_DEFAULT_CENTERS or r2 in ALL_DEFAULT_CENTERS: return True
        for clat, clng in ALL_DEFAULT_CENTERS:
            if abs(lat - clat) < 0.003 and abs(lng - clng) < 0.003:
                return True
        if exp_city in CITY_CENTERS:
            clat, clng = CITY_CENTERS[exp_city]
            if abs(lat - clat) < 0.005 and abs(lng - clng) < 0.005:
                return True
        return False

    profile_dir = os.path.expanduser("~/starup_visualizer/chrome_profile_healer")
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
                
                # Rule 1 Check (outside city or mismatch)
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
                
                # Rule 2 Check (center of city tagging)
                is_r2 = is_center_tagged(lat, lng, exp_city)
                
                if not is_r1 and not is_r2:
                    continue
                
                print(f"\n[HEAL COORDS ONLY] {s_name} ({o_city}) - violates Rule 1={is_r1}, Rule 2={is_r2} | Full Address: \"{addr}\"")
                
                # Paste the full office address directly into the search bar
                query = f"{s_name}, {addr}" if len(addr) < 35 and s_name.lower() not in addr.lower() else addr
                search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
                
                dom_lat, dom_lng = None, None
                try:
                    async with websockets.connect(ws_page_url, max_size=None) as ws_page:
                        navigate_cmd = {
                            "id": 5,
                            "method": "Runtime.evaluate",
                            "params": {"expression": f"window.location.href = '{search_url}'"}
                        }
                        await ws_page.send(json.dumps(navigate_cmd))
                        await ws_page.recv()
                        
                        captcha_detected_once = False
                        for attempt in range(150):
                            await asyncio.sleep(2)
                            get_body = {
                                "id": 2,
                                "method": "Runtime.evaluate",
                                "params": {"expression": "document.body.innerText"}
                            }
                            await ws_page.send(json.dumps(get_body))
                            resp = json.loads(await ws_page.recv())
                            body_text = resp.get("result", {}).get("result", {}).get("value", "")
                            
                            is_captcha = any(kw in body_text.lower() for kw in ["our systems have detected unusual traffic", "unusual traffic", "verifying your request"])
                            if is_captcha and ("do not refresh" in body_text.lower() or "unusual traffic" in body_text.lower()):
                                captcha_detected_once = True
                                print(f"!!! [CAPTCHA DETECTED] Please solve the Google captcha in the opened Chrome window !!!")
                                continue
                            
                            get_html = {
                                "id": 3,
                                "method": "Runtime.evaluate",
                                "params": {"expression": "document.documentElement.outerHTML"}
                            }
                            await ws_page.send(json.dumps(get_html))
                            resp_html = json.loads(await ws_page.recv())
                            page_html = resp_html.get("result", {}).get("result", {}).get("value", "")
                            
                            if page_html:
                                dom_lat, dom_lng = parse_coords_from_dom(page_html)
                                if dom_lat and dom_lng:
                                    print(f"  -> Found GPS coordinates directly in Google Maps DOM: ({dom_lat}, {dom_lng})")
                                    break
                                elif "no results found" in body_text.lower() or attempt >= 3:
                                    break
                            
                            if not captcha_detected_once and attempt >= 5:
                                break
                            
                except Exception as e:
                    print("Error during page communication:", e)
                    
                # NOTE: We NEVER touch or update o["office_address"]. It remains unchanged!
                
                # Coordinate resolution hierarchy (ONLY updating lat & lng)
                resolved = False
                if dom_lat and dom_lng:
                    o["lat"], o["lng"] = round(dom_lat, 7), round(dom_lng, 7)
                    resolved = True
                    print(f"  -> Updated Coordinates via Google DOM: ({o['lat']}, {o['lng']})")
                
                if not resolved:
                    # Tier 2: Call ArcGIS API on exact full address string
                    arc_lat, arc_lng = geocode_arcgis(addr)
                    if not arc_lat and len(addr) < 30:
                        arc_lat, arc_lng = geocode_arcgis(f"{s_name}, {addr}")
                    if arc_lat and arc_lng:
                        o["lat"], o["lng"] = arc_lat, arc_lng
                        resolved = True
                        print(f"  -> Updated Coordinates via ArcGIS API: ({o['lat']}, {o['lng']})")

                if not resolved:
                    # Tier 3: Check Locality Gazetteer against full address string
                    for loc_key, (new_lat, new_lng) in LOCALITY_GAZETTEER.items():
                        if re.search(r"\b" + re.escape(loc_key) + r"\b", addr.lower()):
                            o["lat"], o["lng"] = new_lat, new_lng
                            resolved = True
                            print(f"  -> Updated Coordinates via Locality Gazetteer ('{loc_key}'): ({o['lat']}, {o['lng']})")
                            break

                if resolved:
                    o["location_tagged"] = True
                    healed_count += 1
                else:
                    print("  -> Could not resolve more precise coordinates from address. Leaving coordinates as is.")
                
                if healed_count % 5 == 0:
                    db.save_db()
                
                delay = random.uniform(5.0, 9.0)
                print(f"Waiting {delay:.2f} seconds before next search query...")
                await asyncio.sleep(delay)
                    
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
        print(f"\n=== COORDINATE HEALING COMPLETED (NO ADDRESSES WERE MODIFIED) ===")
        print(f"Total office coordinates updated: {healed_count}")
        
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
