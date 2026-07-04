import json
import os
import requests
import urllib.parse
import time
import re

BLACKLISTED_DOMAINS = {
    "bit.ly", "linktr.ee", "tinyurl.com", "t.co", "buff.ly", "goo.gl", "ow.ly",
    "forms.gle", "google.com", "docs.google.com", "sheets.google.com", "drive.google.com"
}

class DBManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.startups = []
        self.load_db()
        
    def load_db(self):
        if os.path.exists(self.db_path):
            with open(self.db_path, 'r') as f:
                try:
                    self.startups = json.load(f)
                except json.JSONDecodeError:
                    self.startups = []
        else:
            self.startups = []
            
    def save_db(self):
        with open(self.db_path, 'w') as f:
            json.dump(self.startups, f, indent=2)
            
    def find_startup(self, name, logo_domain, target_city=None):
        """
        Find an existing startup by domain first, then by name match.
        """
        normalized_name = self._normalize_text(str(name or ""))
        
        # 1. Match by domain (excluding shorteners and search engines)
        if logo_domain and logo_domain not in BLACKLISTED_DOMAINS:
            for s in self.startups:
                if target_city:
                    s_city = str(s.get("city") or "").lower()
                    if s_city and s_city != "n/a" and target_city.lower() not in s_city and s_city not in target_city.lower():
                        continue
                s_domain = s.get("logo_domain")
                if s_domain and s_domain == logo_domain and s_domain not in BLACKLISTED_DOMAINS:
                    return s
                    
        # 2. Match by normalized name
        for s in self.startups:
            if target_city:
                s_city = str(s.get("city") or "").lower()
                if s_city and s_city != "n/a" and target_city.lower() not in s_city and s_city not in target_city.lower():
                    continue
            if self._normalize_text(str(s.get("name") or "")) == normalized_name:
                return s
                
        return None

    def _sanitize_string(self, text):
        if not isinstance(text, str):
            return text
        # Strip dangerous tags and attributes to prevent XSS injection
        cleaned = re.sub(r'<[^>]*>', '', text)
        return cleaned.strip()

    def merge_startup(self, company_details, jobs, target_city="Bengaluru"):
        """
        Add or update a startup and merge job openings.
        """
        name = self._sanitize_string(company_details.get("name", "N/A"))
        company_details["name"] = name
        if company_details.get("description"):
            company_details["description"] = self._sanitize_string(company_details["description"])
            
        raw_web = company_details.get("website") or ""
        clean_web, clean_dom = self._clean_url_and_domain(raw_web)
        logo_domain = company_details.get("logo_domain") or clean_dom
        if not logo_domain and clean_dom:
            logo_domain = clean_dom
        if clean_web:
            company_details["website"] = clean_web
        if logo_domain:
            company_details["logo_domain"] = logo_domain

        existing = self.find_startup(name, logo_domain, target_city=target_city)
        
        if existing:
            print(f"[DB Manager] Merging existing company: '{existing['name']}' (ID: {existing['id']})")
            if not existing.get("website") and company_details.get("website"):
                existing["website"] = company_details["website"]
            if not existing.get("logo_domain") and company_details.get("logo_domain"):
                existing["logo_domain"] = company_details["logo_domain"]
            if not existing.get("description") and company_details.get("description"):
                existing["description"] = company_details["description"]
            if (not existing.get("funding_stage") or existing.get("funding_stage") == "N/A") and company_details.get("funding_stage"):
                existing["funding_stage"] = company_details["funding_stage"]
            if not existing.get("total_raised") and company_details.get("total_raised"):
                existing["total_raised"] = company_details["total_raised"]
            if company_details.get("is_active_website") is not None:
                existing["is_active_website"] = company_details["is_active_website"]
            if company_details.get("verified_email"):
                existing["verified_email"] = company_details["verified_email"]
            
            if company_details.get("head_count", 0) > existing.get("head_count", 0):
                existing["head_count"] = company_details["head_count"]
                
            is_at_fallback = (
                (existing.get("lat") == 12.9716 and existing.get("lng") == 77.5946) or
                (existing.get("lat") == 12.9767936 and existing.get("lng") == 77.590082) or
                (existing.get("lat") is None or existing.get("lng") is None)
            )
            if is_at_fallback:
                address = company_details.get("bangalore_address") or target_city
                new_lat, new_lng = self.geocode_address(address, existing.get("name"), target_city=target_city)
                if new_lat is not None and new_lng is not None:
                    existing["lat"] = new_lat
                    existing["lng"] = new_lng
                    city_label = address
                    if len(city_label) > 60:
                        city_label = city_label.split(',')[0] + f", {target_city}"
                    existing["city"] = city_label
                
            self._merge_job_openings(existing, jobs)
        else:
            new_id = self._generate_new_id()
            print(f"[DB Manager] Registering NEW company: '{name}' (ID: {new_id})")
            
            address = company_details.get("bangalore_address") or target_city
            lat, lng = self.geocode_address(address, name, target_city=target_city)
            
            city_label = address
            if len(city_label) > 60:
                city_label = city_label.split(',')[0] + f", {target_city}"
            elif not city_label or city_label == "N/A":
                city_label = target_city
            
            new_startup = {
                "id": new_id,
                "name": name,
                "lat": lat,
                "lng": lng,
                "city": city_label,
                "industry": company_details.get("industry") or "Software",
                "description": company_details.get("description") or "",
                "website": company_details.get("website") or "",
                "logo_domain": logo_domain or "",
                "funding_stage": company_details.get("funding_stage") or "Seed / Active",
                "total_raised": company_details.get("total_raised") or "Undisclosed",
                "is_active_website": company_details.get("is_active_website", True),
                "verified_email": company_details.get("verified_email") or "",
                "head_count": company_details.get("head_count") or 10,
                "founders": company_details.get("founders") or [],
                "hr_details": company_details.get("hr_details") or {
                    "contact_email": "",
                    "benefits": ""
                },
                "job_openings": []
            }
            
            # Append jobs
            self._merge_job_openings(new_startup, jobs)
            self.startups.append(new_startup)
            
    def geocode_address(self, address, company_name=None, target_city="Bengaluru"):
        """
        Geocode address using Google Maps API if API key is present.
        Falls back to Nominatim API with heuristic cleaning. Returns (None, None) if unresolved.
        """
        if not address:
            return None, None
            
        # Clean leading noise prefixes
        address = re.sub(r'^\b(primary|headquarters|office|branch|location)\b\s*[:\-]?\s*', '', address, flags=re.IGNORECASE).strip()
            
        # Check if the address is generic (just city name)
        address_clean = address.lower().strip().replace(" ", "").replace(",karnataka", "").replace(",india", "").replace(",in", "")
        is_generic = address_clean in [target_city.lower(), "bengaluru", "bangalore", "hyderabad", "mumbai", "delhi"]
        
        # If the address is generic and we have a company name, try the company name first!
        if is_generic and company_name and company_name != "N/A":
            query_comp = f"{company_name} {target_city}"
            print(f"[Geocoder] Generic address '{address}' detected. Prioritizing direct Company Name Lookup: '{query_comp}'")
            coords = self._geocode_osm(query_comp)
            if self._is_valid_coords(coords):
                return coords
            
        api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
        if api_key:
            print(f"[Geocoder] Attempting Google Maps Geocoding for: '{address}'")
            gmaps_url = "https://maps.googleapis.com/maps/api/geocode/json"
            gmaps_params = {
                "address": address,
                "key": api_key
            }
            backoff = 1.0
            for attempt in range(3):
                try:
                    response = requests.get(gmaps_url, params=gmaps_params, timeout=10)
                    if response.status_code == 429 or response.status_code >= 500:
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("status") == "OK" and data.get("results"):
                            location = data["results"][0]["geometry"]["location"]
                            lat = float(location["lat"])
                            lng = float(location["lng"])
                            print(f"[Geocoder] Google Maps Geocoded successfully -> ({lat}, {lng})")
                            return lat, lng
                        else:
                            print(f"[Geocoder] Google Maps Geocode status failed: {data.get('status')}")
                    break
                except Exception as e:
                    print(f"[Geocoder] Google Maps Geocode exception: {str(e)}")
                    time.sleep(backoff)
                    backoff *= 2
                
        # Fallback to Nominatim OSM Geocoding - Attempt 1A: Company + Address
        if company_name and company_name != "N/A":
            query1a = f"{company_name}, {address}"
            print(f"[Geocoder] Attempting Nominatim Geocoding (Attempt 1A: Company + Address): '{query1a}'")
            coords = self._geocode_osm(query1a)
            if self._is_valid_coords(coords):
                return coords

        # Fallback to Nominatim OSM Geocoding - Attempt 1: Full Address
        print(f"[Geocoder] Attempting Nominatim Geocoding (Full Address): '{address}'")
        coords = self._geocode_osm(address)
        if self._is_valid_coords(coords):
            return coords
            
        # Fallback to Nominatim OSM Geocoding - Attempt 2: First Component + City
        parts = [p.strip() for p in address.split(',')]
        if parts:
            first_comp = self._clean_address_component(parts[0])
            city = target_city
            for p in parts:
                if target_city.lower() in p.lower() or "bangalore" in p.lower() or "bengaluru" in p.lower():
                    city = p
                    break
            
            # Strip zipcodes, state, and country from city if present
            city = re.sub(r'\b(karnataka|maharashtra|telangana|delhi|in|india|\d{6})\b', '', city, flags=re.IGNORECASE)
            city = re.sub(r'\s+', ' ', city).strip()
            
            query2 = f"{first_comp}, {city}"
            print(f"[Geocoder] Attempting Nominatim Geocoding (Attempt 2: First Component + City): '{query2}'")
            coords = self._geocode_osm(query2)
            if self._is_valid_coords(coords):
                return coords
                
        # Fallback to Nominatim OSM Geocoding - Attempt 3: Locality matching
        localities = [
            "hsr", "koramangala", "indiranagar", "indira nagar", "whitefield", "ejipura", 
            "nagawara", "nagavara", "kadubeesanahalli", "domlur", "jp nagar", "jayanagar",
            "manyata", "bagmane", "ecospace", "eco space", "cessna", "bellandur", 
            "electronics city", "electronic city", "outer ring road", "orr", "hebbal", 
            "tech park", "it park", "industrial area", "sez", "estate", "bandra", "andheri", "powai", "gachibowli", "hitec city"
        ]
        
        for part in parts:
            part_clean = self._clean_address_component(part)
            part_normalized = part_clean.lower().replace(" ", "").replace(".", "")
            
            matched = False
            for loc in localities:
                loc_norm = loc.replace(" ", "")
                if loc_norm in part_normalized:
                    matched = True
                    break
                    
            if matched:
                query3 = f"{part_clean}, {target_city}"
                print(f"[Geocoder] Attempting Nominatim Geocoding (Attempt 3: Locality + City): '{query3}'")
                coords = self._geocode_osm(query3)
                if self._is_valid_coords(coords):
                    return coords
                    
        # Fallback to Nominatim OSM Geocoding - Attempt 4: Direct Company Name Lookup
        if company_name and company_name != "N/A":
            query4 = f"{company_name} {target_city}"
            print(f"[Geocoder] Attempting Nominatim Geocoding (Attempt 4: Company Name): '{query4}'")
            coords = self._geocode_osm(query4)
            if self._is_valid_coords(coords):
                return coords

        print(f"[Geocoder] All geocoding attempts failed for '{address}' (Company: '{company_name}'). Leaving coords unresolved (None, None).")
        return None, None

    def _geocode_osm(self, query):
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": query,
            "format": "json",
            "limit": 1
        }
        headers = {
            "User-Agent": "BangaloreStartupVisualizer/1.0 (contact: info@startupvisualizer.com)"
        }
        backoff = 2.0
        for attempt in range(3):
            try:
                # Sleep to satisfy OSM usage policy
                time.sleep(1.2 if attempt == 0 else backoff)
                response = requests.get(url, params=params, headers=headers, timeout=10)
                if response.status_code == 429 or response.status_code >= 500:
                    print(f"  [ OSM Rate limit/Error HTTP {response.status_code} (Attempt {attempt+1}/3). Backing off {backoff}s...")
                    backoff *= 2
                    continue
                if response.status_code == 200 and response.json():
                    loc = response.json()[0]
                    lat = float(loc["lat"])
                    lng = float(loc["lon"])
                    print(f"  -> Geocoded successfully -> ({lat}, {lng})")
                    return lat, lng
                break
            except Exception as e:
                print(f"  -> Geocode exception on attempt {attempt+1}: {str(e)[:40]}")
                time.sleep(backoff)
                backoff *= 2
        return None

    def _clean_address_component(self, comp):
        # Remove floor details, level, primary, numbers
        comp = re.sub(r'\b(primary|floor|floors|level|building|block|suite|stage|cross|landmark|main rd|cross rd|rd|office)\b', '', comp, flags=re.IGNORECASE)
        # Remove symbols like #, numbers like 1st, 2nd, #648/L, Floors 13-16
        comp = re.sub(r'#\S+', '', comp)
        comp = re.sub(r'\b\d+(st|nd|rd|th|f|l)\b', '', comp, flags=re.IGNORECASE)
        # Clean up multiple spaces
        comp = re.sub(r'\s+', ' ', comp).strip()
        return comp

    def _merge_job_openings(self, startup, crawled_jobs):
        """
        Merge jobs list. Check by normalized job title to avoid duplicates.
        """
        existing_jobs = startup.get("job_openings", [])
        for ej in existing_jobs:
            if not ej.get("experience") or ej.get("experience") == "Not disclosed":
                ej["experience"] = "Not specified"
            else:
                ej["experience"] = self._sanitize_string(str(ej["experience"]))
            if not ej.get("salary") or ej.get("salary") == "Not disclosed":
                ej["salary"] = "Not specified"
            else:
                ej["salary"] = self._sanitize_string(str(ej["salary"]))
            if not ej.get("job_type"):
                ej["job_type"] = "Full-time"
            else:
                ej["job_type"] = self._sanitize_string(str(ej["job_type"]))
            if not ej.get("skills") or not isinstance(ej.get("skills"), list):
                ej["skills"] = []
            if not ej.get("posted_date"):
                ej["posted_date"] = "Recent"
            else:
                ej["posted_date"] = self._sanitize_string(str(ej["posted_date"]))
        
        for job in crawled_jobs:
            if not isinstance(job, dict) or not job.get("title"):
                continue
            title = job.get("title")
            norm_title = self._normalize_text(title)
            
            # Check if this job title already exists
            found_job = None
            for ej in existing_jobs:
                if self._normalize_text(ej.get("title", "")) == norm_title:
                    found_job = ej
                    break
                    
            exp = self._sanitize_string(str(job.get("experience", "Not specified")))
            sal = self._sanitize_string(str(job.get("salary", "Not specified")))
            jtype = self._sanitize_string(str(job.get("job_type", "Full-time")))
            skills = [self._sanitize_string(str(s)) for s in job.get("skills", [])] if isinstance(job.get("skills"), list) else []
            pdate = self._sanitize_string(str(job.get("posted_date", "Recent")))

            if found_job:
                if found_job.get("experience") in ("Not specified", "Not disclosed", None, ""):
                    found_job["experience"] = exp
                if found_job.get("salary") in ("Not specified", "Not disclosed", None, ""):
                    found_job["salary"] = sal
                if not found_job.get("job_type"):
                    found_job["job_type"] = jtype
                if not found_job.get("skills"):
                    found_job["skills"] = skills
                if not found_job.get("posted_date") or found_job.get("posted_date") == "Recent":
                    found_job["posted_date"] = pdate
            else:
                clean_title = self._sanitize_string(str(title))
                clean_loc = self._sanitize_string(str(job.get("location") or "Bengaluru"))
                clean_src = self._sanitize_string(str(job.get("source", "LinkedIn")))
                print(f"  + Adding Job opening: '{clean_title}' ({clean_loc})")
                # Deduce department from title
                dept = self._deduce_department(clean_title)
                existing_jobs.append({
                    "title": clean_title,
                    "department": dept,
                    "location": clean_loc,
                    "source": clean_src,
                    "url": job.get("job_url") or job.get("url") or "",
                    "experience": exp,
                    "salary": sal,
                    "job_type": jtype,
                    "skills": skills,
                    "posted_date": pdate
                })
        
        startup["job_openings"] = existing_jobs

    def _deduce_department(self, title):
        title_lower = title.lower()
        if any(k in title_lower for k in ["design", "ui", "ux", "product designer"]):
            return "Design"
        elif any(k in title_lower for k in ["sales", "sdr", "account manager", "bd", "business development"]):
            return "Sales"
        elif any(k in title_lower for k in ["marketing", "seo", "content writer", "growth"]):
            return "Marketing"
        elif any(k in title_lower for k in ["hr", "recruiter", "talent", "people ops"]):
            return "HR / Operations"
        elif any(k in title_lower for k in ["finance", "accountant", "billing"]):
            return "Finance"
        elif any(k in title_lower for k in ["nlp", "ai", "scientist", "research", "machine learning"]):
            return "R&D"
        # Default engineering
        return "Engineering"

    def _clean_url_and_domain(self, url):
        if not url:
            return "", ""
        url = url.strip()
        if 'linkedin.com/redir' in url:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            url = qs.get('url', [url])[0]
        p = urllib.parse.urlparse(url)
        clean_url = urllib.parse.urlunparse((p.scheme, p.netloc, p.path.rstrip('/'), '', '', ''))
        domain = p.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        if domain in BLACKLISTED_DOMAINS:
            return clean_url, ""
        return clean_url, domain

    def _normalize_text(self, text):
        return re.sub(r'[^a-zA-Z0-9]', '', str(text or "")).lower().strip()

    def _generate_new_id(self):
        if not self.startups:
            return 1
        max_id = 0
        for s in self.startups:
            val = s.get("id")
            if val is not None:
                try:
                    int_val = int(val)
                    if int_val > max_id:
                        max_id = int_val
                except (ValueError, TypeError):
                    pass
        return max_id + 1

    def _is_valid_coords(self, coords):
        if not coords:
            return False
        lat, lng = coords
        # Reject if close to fallback center 1
        if abs(lat - 12.9716) < 0.0001 and abs(lng - 77.5946) < 0.0001:
            return False
        # Reject if close to fallback center 2 (OSM city center)
        if abs(lat - 12.9767936) < 0.0001 and abs(lng - 77.590082) < 0.0001:
            return False
        return True
