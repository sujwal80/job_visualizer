#!/usr/bin/env python3
"""
Fast, Browser-Free Precision Geocoding Engine (Esri ArcGIS + Photon + Gazetteer)
Path: data_acquisition/fast_precision_geocoder.py

IRON-CLAD RULES:
1. NEVER modify, edit, or overwrite `office_address` under ANY circumstances. The address text is finalized and immutable.
2. NEVER inject root-level `lat` and `lng` onto top-level startup records.
3. Target all office records currently violating Rule 1 (>80km outside canonical city) or Rule 2 (default city-center tagging).
4. Resolve high-precision latitude & longitude using:
   - Tier 1: Free Esri ArcGIS World Geocoder (full address).
   - Tier 2: Free Esri ArcGIS World Geocoder (simplified address / landmark).
   - Tier 3: Free Photon Elasticsearch Geocoder (Komoot).
   - Tier 4: Local Indian Tech-Park & Locality Gazetteer.
5. Synchronize backend/startups.json and public/static/data/startups.json upon completion.
"""

import os
import sys
import json
import time
import math
import re
import shutil
import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

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

LOCALITY_GAZETTEER = {
    # Bengaluru Tech Parks & Hubs
    "manyata tech park": (13.0487, 77.6209), "manyata": (13.0487, 77.6209), "bagmane": (12.9822, 77.6653),
    "rmz ecoworld": (12.9220, 77.6833), "rmz ecospace": (12.9231, 77.6833), "embassy golf links": (12.9472, 77.6394),
    "prestige tech park": (12.9419, 77.6974), "divyashree": (12.9515, 77.6698), "wework": (12.9716, 77.5946),
    "koramangala": (12.9352, 77.6245), "hsr layout": (12.9121, 77.6446), "indiranagar": (12.9784, 77.6408),
    "whitefield": (12.9698, 77.7500), "bellandur": (12.9304, 77.6784), "electronic city": (12.8452, 77.6602),
    "jayanagar": (12.9308, 77.5838), "jp nagar": (12.9063, 77.5857), "sarjapur": (12.9166, 77.6749),
    "marathahalli": (12.9592, 77.6974), "domlur": (12.9609, 77.6387), "malleshwaram": (13.0031, 77.5703),

    # Mumbai Tech Parks & Hubs
    "solitaire corporate park": (19.1118, 72.8631), "nirlon knowledge park": (19.1557, 72.8596),
    "godrej it park": (19.0913, 72.9232), "hiranandani": (19.1189, 72.9113), "mindspace": (19.1729, 72.8361),
    "bandra kurla complex": (19.0657, 72.8687), "bkc": (19.0657, 72.8687), "andheri east": (19.1155, 72.8715),
    "andheri west": (19.1363, 72.8277), "andheri": (19.1197, 72.8464), "powai": (19.1197, 72.9051),
    "lower parel": (18.9953, 72.8315), "worli": (19.0178, 72.8181), "ghatkopar": (19.0865, 72.9090),
    "vikhroli": (19.1102, 72.9261), "kurla": (19.0728, 72.8797), "malad": (19.1860, 72.8485),
    "bandra": (19.0596, 72.8295), "sakinaka": (19.1013, 72.8885), "navi mumbai": (19.0330, 73.0297),
    "thane": (19.2183, 72.9781),

    # Hyderabad Tech Parks & Hubs
    "raheja mindspace": (17.4428, 78.3820), "t-hub": (17.4445, 78.3772), "knowledge city": (17.4355, 78.3840),
    "hitech city": (17.4435, 78.3772), "hitec city": (17.4435, 78.3772), "gachibowli": (17.4401, 78.3489),
    "madhapur": (17.4483, 78.3915), "jubilee hills": (17.4326, 78.4071), "banjara hills": (17.4156, 78.4357),
    "kondapur": (17.4682, 78.3619), "begumpet": (17.4447, 78.4664), "financial district": (17.4262, 78.3389),
    
    # Pune Tech Parks & Hubs
    "baner": (18.5590, 73.7868), "hinjewadi": (18.5913, 73.7389), "kharadi": (18.5515, 73.9427),
    "viman nagar": (18.5679, 73.9143), "koregaon park": (18.5362, 73.8940), "wakad": (18.5987, 73.7658),
    
    # Delhi NCR
    "dlf cyber city": (28.4950, 77.0895), "cyber city": (28.4950, 77.0895), "udyog vihar": (28.5024, 77.0818),
    "connaught place": (28.6315, 77.2167), "okhla": (28.5320, 77.2721), "nehru place": (28.5494, 77.2522),
    "sector 62": (28.6288, 77.3686), "gurugram": (28.4595, 77.0266), "noida": (28.5355, 77.3910),
    
    # Chennai
    "olympia tech park": (13.0118, 80.2015), "iit-m research park": (12.9915, 80.2435),
    "omr": (12.9229, 80.2319), "guindy": (13.0067, 80.2206), "t nagar": (13.0418, 80.2341),
    "adyar": (13.0012, 80.2565), "velachery": (12.9815, 80.2180), "thoraipakkam": (12.9416, 80.2362),

    # Kolkata
    "salt lake": (22.5867, 88.4172), "sector v": (22.5786, 88.4357), "new town": (22.5958, 88.4795),
    "rajarhat": (22.6200, 88.5100), "biowonder": (22.5128, 88.4011)
}

def haversine(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_expected_city(city_str):
    c_lower = str(city_str or "").lower()
    for k in ["bengaluru", "bangalore"]:
        if k in c_lower: return "bengaluru"
    for k in ["hyderabad"]:
        if k in c_lower: return "hyderabad"
    for k in ["chennai", "madras"]:
        if k in c_lower: return "chennai"
    for k in ["pune"]:
        if k in c_lower: return "pune"
    for k in ["kolkata", "calcutta"]:
        if k in c_lower: return "kolkata"
    for k in ["delhi", "new delhi", "ncr", "gurugram", "gurgaon", "noida"]:
        if k in c_lower: return "delhi_ncr"
    for k in ["mumbai", "bombay"]:
        if k in c_lower: return "mumbai"
    return "other"

def is_center_tagged(lat, lng, exp_city):
    if not lat or not lng: return False
    r1 = (round(lat, 6), round(lng, 6))
    r2 = (round(lat, 4), round(lng, 4))
    if r1 in KNOWN_CENTERS or r2 in KNOWN_CENTERS: return True
    for clat, clng in KNOWN_CENTERS:
        if abs(lat - clat) < 0.003 and abs(lng - clng) < 0.003:
            return True
    if exp_city in CITY_CENTERS:
        clat, clng = CITY_CENTERS[exp_city]
        if abs(lat - clat) < 0.005 and abs(lng - clng) < 0.005:
            return True
    return False

def geocode_arcgis(address):
    """Query Esri ArcGIS World Geocoder."""
    if not address or len(address) < 5:
        return None, None
    url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
    params = {"singleLine": address, "f": "json", "maxLocations": 1, "outFields": "Score"}
    try:
        r = requests.get(url, params=params, timeout=5).json()
        candidates = r.get("candidates", [])
        if candidates and candidates[0].get("score", 0) >= 70:
            loc = candidates[0]["location"]
            lat, lng = loc["y"], loc["x"]
            # Validate within Indian geographic bounds if address appears Indian
            if 6.0 <= lat <= 37.0 and 68.0 <= lng <= 98.0:
                return round(lat, 7), round(lng, 7)
    except Exception:
        pass
    return None, None

def geocode_photon(address):
    """Query Photon (Komoot) Elasticsearch geocoder."""
    if not address or len(address) < 5:
        return None, None
    url = "https://photon.komoot.io/api/"
    params = {"q": address, "limit": 1}
    try:
        r = requests.get(url, params=params, timeout=5).json()
        features = r.get("features", [])
        if features:
            coords = features[0]["geometry"]["coordinates"] # [lng, lat]
            lng, lat = coords[0], coords[1]
            if 6.0 <= lat <= 37.0 and 68.0 <= lng <= 98.0:
                return round(lat, 7), round(lng, 7)
    except Exception:
        pass
    return None, None

def run_fast_geocoding():
    db_path = os.path.join(PROJECT_ROOT, "backend", "startups.json")
    print(f"Loading database from: {db_path}")
    with open(db_path, "r") as f:
        data = json.load(f)

    # Ensure zero root-level coordinate pollution
    for s in data:
        s.pop("lat", None)
        s.pop("lng", None)

    flagged_count = 0
    updated_count = 0

    print("Scanning database for Rule 1 (Outside City >80km) & Rule 2 (Center-of-City Tagging) violations...")
    
    for s in data:
        s_name = str(s.get("name") or "Unknown").strip()
        for o in s.get("offices", []):
            addr = str(o.get("office_address") or "").strip()
            lat = o.get("lat")
            lng = o.get("lng")
            o_city = str(o.get("city") or s.get("city") or "").strip()
            exp_city = get_expected_city(o_city)
            if exp_city == "other":
                continue

            clat, clng = CITY_CENTERS.get(exp_city, (None, None))
            dist = haversine(lat, lng, clat, clng) if clat and lat and lng else 0
            
            is_r1 = clat and dist > 80.0
            is_r2 = not is_r1 and is_center_tagged(lat, lng, exp_city)

            # Check if address is merely generic city name without street level info
            generic_names = [
                "mumbai", "mumbai, maharashtra", "bengaluru", "bengaluru, karnataka",
                "hyderabad", "hyderabad, telangana", "pune", "pune, maharashtra",
                "chennai", "chennai, tamil nadu", "kolkata", "kolkata, west bengal",
                "delhi", "new delhi", "new delhi, delhi", "delhi ncr", "gurugram", "noida"
            ]
            is_generic = addr.lower() in generic_names or (len(addr) < 22 and not any(ch.isdigit() for ch in addr))

            if not is_r1 and not is_r2:
                continue

            # We process if it's out of bounds OR if it's center-tagged with a real detailed address
            if is_r2 and is_generic:
                continue # City center is valid when only city name exists

            flagged_count += 1
            print(f"\n[{flagged_count}] Company: '{s_name}' ({o_city}) | R1={is_r1}, R2={is_r2}")
            print(f"  Full Address: \"{addr}\" | Current Coords: ({lat}, {lng})")

            # NOTE: ZERO edits to o['office_address']. Address is immutable!
            new_lat, new_lng = None, None
            source_engine = ""

            # Tier 1: Esri ArcGIS on full address
            new_lat, new_lng = geocode_arcgis(addr)
            if new_lat and new_lng and (not clat or haversine(new_lat, new_lng, clat, clng) <= 80.0):
                source_engine = "Esri ArcGIS (Full Address)"

            # Tier 2: Esri ArcGIS on cleaned/simplified building address
            if not source_engine:
                simplified = re.sub(r'\b(?:no\.|number|flat|door|unit|suite|room|cabin|floor|flr|plot|bldg|building|tower|wing)\s*[\w\d\-\/\&]+\b', '', addr, flags=re.I)
                simplified = re.sub(r'\s+', ' ', simplified).strip(' ,.-')
                if simplified and simplified != addr and len(simplified) > 5:
                    new_lat, new_lng = geocode_arcgis(simplified)
                    if new_lat and new_lng and (not clat or haversine(new_lat, new_lng, clat, clng) <= 80.0):
                        source_engine = "Esri ArcGIS (Simplified Landmark)"

            # Tier 3: Photon Elasticsearch Geocoder
            if not source_engine:
                new_lat, new_lng = geocode_photon(addr)
                if new_lat and new_lng and (not clat or haversine(new_lat, new_lng, clat, clng) <= 80.0):
                    source_engine = "Photon Komoot (Elasticsearch)"

            # Tier 4: Locality Gazetteer lookup
            if not source_engine:
                for loc_key, (g_lat, g_lng) in LOCALITY_GAZETTEER.items():
                    if re.search(r"\b" + re.escape(loc_key) + r"\b", addr.lower()):
                        new_lat, new_lng = g_lat, g_lng
                        source_engine = f"Locality Gazetteer ('{loc_key}')"
                        break

            if source_engine and new_lat and new_lng:
                o["lat"], o["lng"] = round(new_lat, 7), round(new_lng, 7)
                o["location_tagged"] = True
                updated_count += 1
                print(f"  -> RESOLVED via {source_engine}: ({o['lat']}, {o['lng']})")
            else:
                print(f"  -> Could not improve precision beyond current coordinate. Retained ({lat}, {lng})")

            time.sleep(0.3) # Fast 300ms pacing for courteous API usage

    print(f"\n=== PRECISION GEOCODING COMPLETE ===")
    print(f"Flagged problematic detailed offices: {flagged_count}")
    print(f"Successfully healed with precision GPS coordinates: {updated_count}")

    with open(db_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved updated database to: {db_path}")

    public_db_path = os.path.join(PROJECT_ROOT, "public", "static", "data", "startups.json")
    os.makedirs(os.path.dirname(public_db_path), exist_ok=True)
    shutil.copy2(db_path, public_db_path)
    print(f"Synchronized database to: {public_db_path}")

if __name__ == "__main__":
    run_fast_geocoding()
