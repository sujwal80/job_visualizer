"""
Startup Domain Business Logic & Data Service
Houses functions for loading startup records from the filesystem, caching in memory,
filtering and sorting against viewport queries and metadata criteria, and formatting lean payloads.
"""

import os
import json
from backend.utils.validators import _safe_float, _check_has_pin, _sanitize_string, _sanitize_url, _strip_redundant
from backend.utils.compatibility import safe_flock, LOCK_SH, LOCK_UN, JSRequest as Request

from backend import config

DATA_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'startups.json'))

# In-memory database cache to prevent redundant disk I/O across API requests
_cache_data = None
_cache_mtime = 0
_cache_startups = None

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
            
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            safe_flock(f, LOCK_SH)
            try:
                data = json.load(f)
            finally:
                safe_flock(f, LOCK_UN)

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

def filter_and_sort_startups(startups, min_lat, max_lat, min_lng, max_lng, limit, city_query="", skill_query="", industry_query="", search_query="", dept_query="", exp_query="", has_jobs=False, role_query="", salary_min_query=None, exp_level_query="", work_type_query=""):
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
            # Preserve unpinned remote startups only at wide zoom levels (lat_span >= 1.0)
            lat_span = abs(max_lat - min_lat)
            if s.get("has_pin") is False:
                if lat_span < 1.0:
                    continue
            else:
                eff_lat = lat if lat is not None else config.DEFAULT_MAP_CENTER_LAT
                eff_lng = lng if lng is not None else config.DEFAULT_MAP_CENTER_LNG
                if eff_lat < min_lat or eff_lat > max_lat or eff_lng < min_lng or eff_lng > max_lng:
                    continue
        if city_query:
            import re
            city_query_clean = city_query.strip().lower()
            city_val = str(s.get("city") or s.get("location") or "").lower()
            
            # Dynamically match country-level and regional city queries to their respective hubs in dataset
            is_match = False
            for _region_key, _syn_set in config.REGION_SYNONYM_MAP.items():
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
            tokens = [t.lower() for t in search_query.split()]
            if tokens:
                startup_matches = True
                for token in tokens:
                    name_val = str(s.get("name") or "").lower()
                    desc_val = str(s.get("description") or "").lower()
                    city_val = str(s.get("city") or s.get("location") or "").lower()
                    
                    token_matched = (token in name_val or token in desc_val or token in city_val)
                    
                    if not token_matched:
                        s_skills = s.get("skills")
                        if isinstance(s_skills, list):
                            token_matched = any(token in str(sk).lower() for sk in s_skills if sk is not None)
                        elif isinstance(s_skills, str):
                            token_matched = token in s_skills.lower()
                    
                    if not token_matched:
                        founder_names = [str(f.get("name") or "").lower() for f in (s.get("founders") or []) if isinstance(f, dict)]
                        token_matched = any(token in fn for fn in founder_names)
                    
                    if not token_matched:
                        for j in (s.get("job_openings") or []):
                            if not isinstance(j, dict):
                                continue
                            j_title = str(j.get("title") or "").lower()
                            j_dept = str(j.get("department") or "").lower()
                            j_salary = str(j.get("salary") or "").lower()
                            j_exp = str(j.get("experience") or "").lower()
                            j_skills = j.get("skills") or []
                            
                            if (token in j_title or 
                                token in j_dept or 
                                token in j_salary or 
                                token in j_exp or
                                (isinstance(j_skills, list) and any(token in str(sk).lower() for sk in j_skills if isinstance(sk, str)))):
                                token_matched = True
                                break
                    
                    if not token_matched:
                        startup_matches = False
                        break
                        
                if not startup_matches:
                    continue
        has_job_filters = bool(role_query or salary_min_query is not None or exp_level_query or work_type_query)
        job_openings = s.get("job_openings") or []
        
        filtered_jobs = []
        for j in job_openings:
            if not isinstance(j, dict):
                continue
            if role_query and role_query not in str(j.get("title") or "").lower():
                continue
            if salary_min_query is not None:
                max_sal = _parse_max_salary(j.get("salary"))
                if max_sal is None or max_sal < salary_min_query:
                    continue
            if exp_level_query and not _match_exp_level(str(j.get("experience") or ""), exp_level_query):
                continue
            if work_type_query and not _match_work_type(j, work_type_query, is_remote_office=s.get("is_remote_office")):
                continue
            filtered_jobs.append(j)

        if has_job_filters:
            if not filtered_jobs:
                continue
            s_copy = dict(s)
            s_copy["job_openings"] = filtered_jobs
        else:
            s_copy = s

        effective_jobs = s_copy.get("job_openings") or s_copy.get("jobs") or []
        if dept_query:
            if not any(dept_query in str(j.get("department") or "").lower() for j in effective_jobs if isinstance(j, dict)):
                continue
        if exp_query:
            if not any(exp_query in str(j.get("experience") or "").lower() or exp_query in str(j.get("job_type") or "").lower() for j in effective_jobs if isinstance(j, dict)):
                continue
        if has_jobs:
            job_cnt = len(effective_jobs) if len(effective_jobs) > 0 else (s_copy.get("job_count") or 0)
            if job_cnt == 0:
                continue
        filtered.append(s_copy)
        
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
        "lat": lat_val if lat_val is not None else config.DEFAULT_MAP_CENTER_LAT,
        "lng": lng_val if lng_val is not None else config.DEFAULT_MAP_CENTER_LNG,
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
                "location": _sanitize_string(j.get("location") or s_copy.get("city") or config.DEFAULT_TARGET_CITY),
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
        "lat": lat_val if lat_val is not None else config.DEFAULT_MAP_CENTER_LAT,
        "lng": lng_val if lng_val is not None else config.DEFAULT_MAP_CENTER_LNG,
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
    Retrieve the dataset version derived from the disk file modification timestamp of startups.json,
    falling back to a static version string in edge worker environments.

    Returns:
        str: String representation of int(mtime) of DATA_FILE, or "v1.0.0" if file missing or error occurs.
    """
    try:
        if os.path.exists(DATA_FILE):
            return str(int(os.path.getmtime(DATA_FILE)))
    except Exception:
        pass
    return "v1.0.0"

async def load_startups_from_assets(assets_binding):
    """
    Load startup records from Cloudflare Pages static ASSETS binding.
    """
    global _cache_startups
    if _cache_startups is not None:
        return _cache_startups


    req = Request.new("http://assets/static/data/startups.json")
    resp = await assets_binding.fetch(req)
    
    # Check if resp is mock or real
    if hasattr(resp, "json"):
        data = await resp.json()
    else:
        # standard mock fallback in case mock doesn't support json method as a coroutine
        data = resp

    if not isinstance(data, list):
        try:
            if hasattr(data, "to_py"):
                data = data.to_py()
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

    _cache_startups = data
    return data


async def load_startups_unified(env=None):
    """
    Unified helper to load startup records.
    If env is provided and contains Pages static assets binding (`ASSETS`),
    call and return the result of `await load_startups_from_assets(assets_binding)`.
    Otherwise, fall back to synchronous `load_startups()`.
    """
    assets_binding = None
    if env is not None:
        if isinstance(env, dict):
            assets_binding = env.get("ASSETS")
        elif hasattr(env, "ASSETS"):
            assets_binding = getattr(env, "ASSETS")

    if assets_binding is not None:
        return await load_startups_from_assets(assets_binding)
    return load_startups()


def _parse_max_salary(salary_str):
    if not salary_str:
        return None
    s = salary_str.strip().lower()
    if any(x in s for x in ["not specified", "not disclosed", "undisclosed", "competitive", "negotiable"]):
        return None
    
    s = s.replace("₹", "").replace(",", "")
    
    import re
    numbers = [float(x) for x in re.findall(r'\d+\.?\d*', s)]
    if not numbers:
        return None
    
    processed_numbers = []
    for num in numbers:
        if num >= 1000:
            processed_numbers.append(num / 100000.0)
        else:
            processed_numbers.append(num)
            
    return max(processed_numbers) if processed_numbers else None


def _parse_experience_years(exp_str):
    if not exp_str:
        return None, None
    s = exp_str.strip().lower()
    if s in ("fresher", "entry"):
        return 0, 0
    if "not specified" in s or "not disclosed" in s:
        return None, None
    
    import re
    numbers = [int(x) for x in re.findall(r'\d+', s)]
    if not numbers:
        return None, None
        
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    elif "+" in s or "above" in s or "more" in s:
        return numbers[0], 100
    else:
        return numbers[0], numbers[0]


def _match_exp_level(exp_str, exp_level_query):
    if not exp_level_query:
        return True
    q = exp_level_query.strip().lower()
    
    try:
        q_num = float(q)
        min_years, max_years = _parse_experience_years(exp_str)
        if min_years is None:
            return False
        return min_years <= q_num <= max_years
    except ValueError:
        min_years, max_years = _parse_experience_years(exp_str)
        if min_years is None:
            return q in exp_str.strip().lower()
            
        if q in ("entry", "fresher"):
            return min_years <= 2
        elif q in ("mid", "intermediate"):
            return min_years < 5 and max_years >= 2
        elif q in ("senior", "lead"):
            return min_years >= 5
        else:
            return q in exp_str.strip().lower()


def _match_work_type(job, work_type_query, is_remote_office=None):
    if not work_type_query:
        return True
    q = work_type_query.strip().lower()
    
    job_type = str(job.get("job_type") or "").lower()
    location = str(job.get("location") or "").lower()
    title = str(job.get("title") or "").lower()
    
    has_remote = "remote" in job_type or "remote" in location or "remote" in title
    has_hybrid = "hybrid" in job_type or "hybrid" in location or "hybrid" in title
    has_onsite = any(keyword in job_type or keyword in location or keyword in title for keyword in ("onsite", "on-site", "in-office", "in office"))
    
    if q == "remote":
        if has_onsite:
            return False
        if has_remote:
            return True
        if not has_remote and not has_hybrid:
            if is_remote_office is True:
                return True
        return False
        
    if q == "hybrid":
        return has_hybrid
        
    if q in ("on-site", "onsite"):
        if has_onsite:
            return True
        if has_remote or has_hybrid:
            return False
        if is_remote_office is True:
            return False
        return True
        
    return q in location


