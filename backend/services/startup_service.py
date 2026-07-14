"""
Startup Domain Business Logic & Data Service
Houses functions for loading startup records from the filesystem, caching in memory,
filtering and sorting against viewport queries and metadata criteria, and formatting lean payloads.
"""

import os
import json
from backend.utils.validators import _safe_float, _check_has_pin, _sanitize_string, _sanitize_url, _strip_redundant
try:
    from backend.config import DEFAULT_MAP_CENTER_LAT, DEFAULT_MAP_CENTER_LNG, DEFAULT_TARGET_CITY, REGION_SYNONYM_MAP
except ImportError:
    from config import DEFAULT_MAP_CENTER_LAT, DEFAULT_MAP_CENTER_LNG, DEFAULT_TARGET_CITY, REGION_SYNONYM_MAP

DATA_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'startups.json'))

# In-memory database cache to prevent redundant disk I/O across API requests
_cache_data = None
_cache_mtime = 0

def load_startups():
    """
    Load startup records from the JSON filesystem database with mtime-based in-memory caching.

    Uses shared read flock to prevent reading partially written or truncated files.

    Returns:
        list: A list of sanitized startup dictionary objects.
    """
    global _cache_data, _cache_mtime
    if not os.path.exists(DATA_FILE):
        return []
    try:
        current_mtime = os.path.getmtime(DATA_FILE)
        # Return cached dataset if file modification timestamp hasn't changed
        if _cache_data is not None and current_mtime == _cache_mtime:
            return _cache_data
            
        try:
            import fcntl
            HAS_FCNTL = True
        except ImportError:
            HAS_FCNTL = False

        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            if HAS_FCNTL:
                try:
                    fcntl.flock(f, fcntl.LOCK_SH)
                except Exception:
                    pass
            try:
                data = json.load(f)
            finally:
                if HAS_FCNTL:
                    try:
                        fcntl.flock(f, fcntl.LOCK_UN)
                    except Exception:
                        pass

            if not isinstance(data, list):
                data = []
            for s in data:
                if not isinstance(s, dict):
                    continue
                s["has_pin"] = _check_has_pin(s)
                for f_key in ["name", "city", "description", "industry", "funding_stage", "total_raised", "verified_email"]:
                    if f_key in s:
                        s[f_key] = _sanitize_string(s[f_key])
                if "website" in s:
                    s["website"] = _sanitize_url(s.get("website"))
                if "url" in s:
                    s["url"] = _sanitize_url(s.get("url"))
                for f_obj in (s.get("founders") or []):
                    if isinstance(f_obj, dict):
                        if "name" in f_obj:
                            f_obj["name"] = _sanitize_string(f_obj.get("name"))
                        if "linkedin" in f_obj:
                            f_obj["linkedin"] = _sanitize_url(f_obj.get("linkedin"))
                for j_obj in (s.get("job_openings") or []):
                    if isinstance(j_obj, dict):
                        for j_key in ["title", "department", "experience", "salary", "job_type", "location", "posted_date", "source"]:
                            if j_key in j_obj:
                                j_obj[j_key] = _sanitize_string(j_obj[j_key])
                        if "url" in j_obj:
                            j_obj["url"] = _sanitize_url(j_obj.get("url"))
                        if isinstance(j_obj.get("skills"), list):
                            j_obj["skills"] = [_sanitize_string(sk) for sk in j_obj["skills"] if isinstance(sk, str)]
            _cache_data = data
            _cache_mtime = current_mtime
            return data
    except Exception:
        return _cache_data or []

def filter_and_sort_startups(startups, min_lat, max_lat, min_lng, max_lng, limit, city_query="", skill_query="", industry_query="", search_query="", dept_query="", exp_query="", has_jobs=False):
    """
    Filter and sort startup records by geographic viewport bounding boxes and text criteria.

    Remote or unpinned startups (`has_pin=False`) are preserved across geographic queries
    so remote job opportunities remain discoverable anywhere on the map.

    Args:
        startups (list): The full list of startup dictionaries to filter.
        min_lat (float or None): Southern latitude boundary of the viewport.
        max_lat (float or None): Northern latitude boundary of the viewport.
        min_lng (float or None): Western longitude boundary of the viewport.
        max_lng (float or None): Eastern longitude boundary of the viewport.
        limit (int): Maximum number of startup records to return (slicing limit).
        city_query (str): Case-insensitive substring filter for city/location.
        skill_query (str): Case-insensitive substring filter across startup and job skills.
        industry_query (str): Case-insensitive substring filter for industry classification.
        search_query (str): Case-insensitive search string matching names, descriptions, founders, or jobs.
        dept_query (str): Case-insensitive substring filter for job department.
        exp_query (str): Case-insensitive substring filter for job experience/type.

    Returns:
        list: The filtered, sorted list of startup dictionaries capped at `limit`.
    """
    filtered = []
    for s in startups:
        lat = _safe_float(s.get("lat"))
        lng = _safe_float(s.get("lng"))
        if min_lat is not None and max_lat is not None and min_lng is not None and max_lng is not None:
            # Preserve unpinned remote startups regardless of map bounding box
            if s.get("has_pin") is False:
                pass
            else:
                eff_lat = lat if lat is not None else DEFAULT_MAP_CENTER_LAT
                eff_lng = lng if lng is not None else DEFAULT_MAP_CENTER_LNG
                if eff_lat < min_lat or eff_lat > max_lat or eff_lng < min_lng or eff_lng > max_lng:
                    continue
        if city_query:
            import re
            city_query_clean = city_query.strip().lower()
            city_val = str(s.get("city") or s.get("location") or "").lower()
            
            # Dynamically match country-level and regional city queries to their respective hubs in dataset
            is_match = False
            for _region_key, _syn_set in REGION_SYNONYM_MAP.items():
                if city_query_clean in _syn_set:
                    if any(syn in city_val for syn in _syn_set):
                        is_match = True
                        break

            if not is_match:
                normalized_query = re.sub(r',\s*[a-z\s]+$', '', city_query_clean).strip()
                comp_query = normalized_query.replace("bangalore", "bengaluru")
                comp_city = city_val.replace("bangalore", "bengaluru")
                if comp_query not in comp_city and city_query_clean not in comp_city:
                    continue
        if skill_query:
            s_skills = []
            if isinstance(s.get("skills"), list):
                s_skills.extend([str(sk).lower() for sk in s.get("skills") if sk is not None])
            elif isinstance(s.get("skills"), str):
                s_skills.append(s.get("skills").lower())
            for j in (s.get("job_openings") or []):
                if isinstance(j, dict) and isinstance(j.get("skills"), list):
                    s_skills.extend([str(sk).lower() for sk in j.get("skills") if sk is not None])
            if not any(skill_query in sk for sk in s_skills):
                continue
        if industry_query:
            industry_val = str(s.get("industry") or "").lower()
            if industry_query not in industry_val:
                continue
        if search_query:
            name_val = str(s.get("name") or "").lower()
            desc_val = str(s.get("description") or "").lower()
            city_val = str(s.get("city") or s.get("location") or "").lower()
            founder_names = [str(f.get("name") or "").lower() for f in (s.get("founders") or []) if isinstance(f, dict)]
            
            job_matches = False
            for j in (s.get("job_openings") or []):
                if not isinstance(j, dict):
                    continue
                j_title = str(j.get("title") or "").lower()
                j_dept = str(j.get("department") or "").lower()
                j_skills = [str(sk).lower() for sk in (j.get("skills") or []) if isinstance(sk, str)]
                j_salary = str(j.get("salary") or "").lower()
                j_exp = str(j.get("experience") or "").lower()
                if (search_query in j_title or 
                    search_query in j_dept or 
                    any(search_query in sk for sk in j_skills) or 
                    search_query in j_salary or 
                    search_query in j_exp):
                    job_matches = True
                    break
            
            if not (search_query in name_val or 
                    search_query in desc_val or 
                    search_query in city_val or 
                    any(search_query in fn for fn in founder_names) or 
                    job_matches):
                continue
        if dept_query:
            jobs = s.get("job_openings") or []
            if not any(dept_query in str(j.get("department") or "").lower() for j in jobs if isinstance(j, dict)):
                continue
        if exp_query:
            jobs = s.get("job_openings") or []
            if not any(exp_query in str(j.get("experience") or "").lower() or exp_query in str(j.get("job_type") or "").lower() for j in jobs if isinstance(j, dict)):
                continue
        if has_jobs:
            jobs = s.get("job_openings") or s.get("jobs") or []
            job_cnt = len(jobs) if len(jobs) > 0 else (s.get("job_count") or 0)
            if job_cnt == 0:
                continue
        filtered.append(s)
        
    # Sort startups descending by active job opening count
    filtered.sort(key=lambda x: len(x.get("job_openings") or x.get("jobs") or []), reverse=True)
    if not has_jobs and limit >= 0:
        filtered = filtered[:limit]
    return filtered

def format_startup_summary(s):
    """
    Format a lightweight summary payload for a startup, pruning heavy raw job arrays.

    Used by `/api/companies` list endpoints to minimize network payload size and improve DOM rendering speed.

    Args:
        s (dict): The full startup record dictionary.

    Returns:
        dict: A lightweight summary dictionary optimized for list and map marker rendering.
    """
    logo_domain = s.get("logo_domain", "")
    logo_svg_url = s.get("logo_svg_url", "")
    logo_url = logo_svg_url if logo_svg_url else ""
    website = _sanitize_url(s.get("website", ""))
    
    job_openings = s.get("job_openings") or []
    experiences = list({_sanitize_string(j.get("experience")) for j in job_openings if isinstance(j, dict) and j.get("experience") and j.get("experience") != "Not specified"})
    salaries = list({_sanitize_string(j.get("salary")) for j in job_openings if isinstance(j, dict) and j.get("salary") and j.get("salary") != "Not disclosed"})
    job_types = list({_sanitize_string(j.get("job_type")) for j in job_openings if isinstance(j, dict) and j.get("job_type")})
    all_skills = set()
    for j in job_openings:
        if isinstance(j, dict) and isinstance(j.get("skills"), list):
            for skill in j.get("skills"):
                if isinstance(skill, str):
                    all_skills.add(skill.strip())
    skills = list(all_skills)

    has_pin_val = s.get("has_pin", True)
    lat_val = _safe_float(s.get("lat"))
    lng_val = _safe_float(s.get("lng"))

    return {
        "id": s.get("id"),
        "name": _sanitize_string(s.get("name")),
        "lat": lat_val if lat_val is not None else DEFAULT_MAP_CENTER_LAT,
        "lng": lng_val if lng_val is not None else DEFAULT_MAP_CENTER_LNG,
        "city": _sanitize_string(s.get("city")),
        "experience": experiences,
        "salary": salaries,
        "job_type": job_types,
        "skills": skills,
        "logo_url": logo_url,
        "url": website,
        "description": _sanitize_string(s.get("description"))[:120],
        "has_pin": has_pin_val,
        "industry": _sanitize_string(s.get("industry")),
        "head_count": s.get("head_count"),
        "logo_domain": logo_domain,
        "website": website,
        "funding_stage": _sanitize_string(s.get("funding_stage", "Seed / Active")),
        "total_raised": _sanitize_string(s.get("total_raised", "Undisclosed")),
        "is_active_website": s.get("is_active_website", True),
        "verified_email": _sanitize_string(s.get("verified_email")),
        "job_count": len(job_openings),
        "job_titles": [_sanitize_string(j.get("title", "")) for j in job_openings if isinstance(j, dict)],
        "founder_names": [_sanitize_string(f.get("name", "")) for f in (s.get("founders") or []) if isinstance(f, dict)]
    }

def format_startup_details(s):
    """
    Format a comprehensive detail payload for a specific startup, including structured job listings.

    Used by `/api/companies/<id>` endpoints to populate details sidebars and modal views.

    Args:
        s (dict): The full startup record dictionary.

    Returns:
        dict: A sanitized, detailed dictionary including individual job opening objects.
    """
    s_copy = dict(s)
    for field in ["name", "city", "description", "industry", "funding_stage", "total_raised", "verified_email"]:
        if field in s_copy:
            s_copy[field] = _sanitize_string(s_copy[field])

    logo_domain = s_copy.get("logo_domain", "")
    logo_svg_url = s_copy.get("logo_svg_url", "")
    s_copy["logo_url"] = logo_svg_url if logo_svg_url else ""
    s_copy["url"] = _sanitize_url(s_copy.get("website", ""))
    if "website" in s_copy:
        s_copy["website"] = _sanitize_url(s_copy.get("website", ""))
    
    job_openings = s_copy.pop("job_openings", None) or []
    clean_jobs = []
    for j in job_openings:
        if isinstance(j, dict):
            clean_jobs.append({
                "title": _sanitize_string(j.get("title")),
                "url": _sanitize_url(j.get("url", "")),
                "department": _sanitize_string(j.get("department", "General")),
                "experience": _sanitize_string(j.get("experience")),
                "salary": _sanitize_string(j.get("salary")),
                "job_type": _sanitize_string(j.get("job_type")),
                "skills": [_sanitize_string(sk) for sk in (j.get("skills") or []) if isinstance(sk, str)],
                "location": _sanitize_string(j.get("location") or s_copy.get("city") or DEFAULT_TARGET_CITY),
                "posted_date": _sanitize_string(j.get("posted_date", "Active")),
                "source": _sanitize_string(j.get("source", "Direct"))
            })
    s_copy["jobs"] = clean_jobs
    s_copy["job_count"] = len(clean_jobs)

    s_copy["experience"] = list({j.get("experience") for j in clean_jobs if j.get("experience") and j.get("experience") != "Not specified"})
    s_copy["salary"] = list({j.get("salary") for j in clean_jobs if j.get("salary") and j.get("salary") != "Not disclosed"})
    s_copy["job_type"] = list({j.get("job_type") for j in clean_jobs if j.get("job_type")})
    all_skills = set()
    for j in clean_jobs:
        if isinstance(j.get("skills"), list):
            for skill in j.get("skills"):
                if isinstance(skill, str):
                    all_skills.add(skill.strip())
    s_copy["skills"] = list(all_skills)

    if "founders" in s_copy and isinstance(s_copy["founders"], list):
        clean_founders = []
        for f in (s_copy["founders"] or []):
            if isinstance(f, dict):
                f_copy = dict(f)
                if "name" in f_copy:
                    f_copy["name"] = _sanitize_string(f_copy.get("name"))
                if "linkedin" in f_copy:
                    f_copy["linkedin"] = _sanitize_url(f_copy.get("linkedin"))
                clean_founders.append(f_copy)
            else:
                clean_founders.append(f)
        s_copy["founders"] = clean_founders

    return _strip_redundant(s_copy)

def format_lightweight_summary(s):
    """
    Format a lightweight summary payload (9 fields) for a startup when has_jobs=true.

    Used by `/api/companies?has_jobs=true` to minimize network payload size and improve map plotting speed.

    Args:
        s (dict): The startup record dictionary.

    Returns:
        dict: A lightweight summary dictionary containing 9 fields:
              id, name, lat, lng, city, logo_url, industry, job_count, has_pin.
    """
    logo_domain = s.get("logo_domain", "")
    logo_svg_url = s.get("logo_svg_url", "")
    logo_url = logo_svg_url if logo_svg_url else ""
    has_pin_val = s.get("has_pin", True)
    lat_val = _safe_float(s.get("lat"))
    lng_val = _safe_float(s.get("lng"))
    jobs = s.get("job_openings") or s.get("jobs") or []
    job_count = len(jobs) if len(jobs) > 0 else (s.get("job_count") or 0)
    return {
        "id": s.get("id"),
        "name": _sanitize_string(s.get("name")),
        "lat": lat_val if lat_val is not None else DEFAULT_MAP_CENTER_LAT,
        "lng": lng_val if lng_val is not None else DEFAULT_MAP_CENTER_LNG,
        "city": _sanitize_string(s.get("city")),
        "logo_url": logo_url,
        "industry": _sanitize_string(s.get("industry")),
        "job_count": job_count,
        "has_pin": has_pin_val,
        "head_count": s.get("head_count"),
        "funding_stage": _sanitize_string(s.get("funding_stage", "Seed / Active")),
        "verified_email": _sanitize_string(s.get("verified_email")),
        "founder_names": [_sanitize_string(f.get("name", "")) for f in (s.get("founders") or []) if isinstance(f, dict)]
    }

def get_data_version():
    """
    Retrieve the dataset version derived from the disk file modification timestamp of startups.json.

    Returns:
        str: String representation of int(mtime) of DATA_FILE, or "0" if file missing or error occurs.
    """
    try:
        if os.path.exists(DATA_FILE):
            return str(int(os.path.getmtime(DATA_FILE)))
    except Exception:
        pass
    return "0"

