from flask import Flask, jsonify, render_template, request, make_response, g
import json
import os
import time
import math
import gzip
import io
import re
from collections import defaultdict
from werkzeug.middleware.proxy_fix import ProxyFix

def _sanitize_string(val):
    if val is None:
        return ""
    if not isinstance(val, str):
        return val
    cleaned = re.sub(r'<[^>]*>', '', val)
    return cleaned.strip()

def _safe_float(val, default=None):
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default

REQUIRED_FIELDS = {
    'id', 'name', 'lat', 'lng', 'city', 'experience', 
    'salary', 'job_type', 'skills', 'logo_url', 'url', 'description'
}

app = Flask(
    __name__, 
    static_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend', 'static'),
    template_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend', 'templates')
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

DATA_FILE = os.path.join(os.path.dirname(__file__), 'startups.json')

# In-memory database cache
_cache_data = None
_cache_mtime = 0

# Simple IP-based token bucket rate limiter (120 req/min)
_rate_limits = defaultdict(list)

def _check_rate_limit(ip, limit=120, window=60):
    now = time.time()
    reqs = _rate_limits[ip]
    _rate_limits[ip] = [t for t in reqs if now - t < window]
    count = len(_rate_limits[ip])
    if limit <= 0 or count >= limit:
        oldest = _rate_limits[ip][0] if _rate_limits[ip] else now
        retry_after = max(1, int(math.ceil((oldest + window) - now)))
        return False, retry_after, 0, max(0, limit)
    _rate_limits[ip].append(now)
    return True, 0, limit - len(_rate_limits[ip]), limit

def _check_has_pin(s):
    lat = _safe_float(s.get("lat"))
    lng = _safe_float(s.get("lng"))
    if lat is None or lng is None:
        return False
    if (abs(lat - 12.9716) < 0.008 and abs(lng - 77.5946) < 0.008) or (abs(lat - 12.9767) < 0.008 and abs(lng - 77.5900) < 0.008):
        return False
    addr = str(s.get("bangalore_address") or s.get("address") or s.get("city") or "").strip().lower()
    if addr in ["bengaluru", "bangalore", "india", "karnataka", "bengaluru, karnataka"]:
        return False
    return True

def _sanitize_url(url):
    if not url or not isinstance(url, str):
        return ""
    url_clean = url.strip()
    lower = url_clean.lower()
    if lower.startswith("javascript:") or lower.startswith("data:") or lower.startswith("vbscript:"):
        return ""
    return url_clean

def load_startups():
    global _cache_data, _cache_mtime
    if not os.path.exists(DATA_FILE):
        return []
    try:
        current_mtime = os.path.getmtime(DATA_FILE)
        if _cache_data is not None and current_mtime == _cache_mtime:
            return _cache_data
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
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

def _validate_query_params(args):
    allowed_params = {'min_lat', 'max_lat', 'min_lng', 'max_lng', 'limit', 'city', 'skill', 'industry'}
    for key in args.keys():
        if key not in allowed_params:
            return False, f"Unsupported query parameter: '{key}'"
        for val in args.getlist(key):
            if len(val) > 100 and key != 'limit':
                return False, f"Parameter '{key}' exceeds maximum length of 100"
            lower = val.lower()
            if "<script" in lower or "<" in lower or ">" in lower or "' or '" in lower or '" or "' in lower:
                return False, f"Parameter '{key}' contains invalid characters or injection attempts"

    float_bounds = {
        'min_lat': (-90.0, 90.0), 'max_lat': (-90.0, 90.0),
        'min_lng': (-180.0, 180.0), 'max_lng': (-180.0, 180.0)
    }
    for param, (low, high) in float_bounds.items():
        if param in args:
            for item in args.getlist(param):
                if item != '':
                    try:
                        val = float(item)
                        if math.isnan(val) or math.isinf(val) or val < low or val > high:
                            return False, f"Parameter '{param}' out of bounds [{low}, {high}]"
                    except (ValueError, TypeError):
                        return False, f"Parameter '{param}' must be a valid numeric float"
    
    if 'limit' in args:
        for item in args.getlist('limit'):
            if item != '':
                try:
                    val = int(item)
                    if val < 0 or val > 5000:
                        return False, "Parameter 'limit' must be an integer between 0 and 5000"
                except (ValueError, TypeError):
                    return False, "Parameter 'limit' must be a valid integer"
            
    return True, None

def _strip_redundant(obj):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    elif isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                v = 0.0 if k in ('lat', 'lng') else None
            if k in REQUIRED_FIELDS:
                cleaned[k] = _strip_redundant(v) if isinstance(v, (dict, list)) else (v if v is not None else "")
            else:
                if v is None:
                    cleaned[k] = ""
                elif v == [] or v == {}:
                    continue
                else:
                    if isinstance(v, (dict, list)):
                        nested = _strip_redundant(v)
                        if nested is not None and nested != [] and nested != {}:
                            cleaned[k] = nested
                    else:
                        cleaned[k] = v
        return cleaned
    elif isinstance(obj, list):
        return [_strip_redundant(x) for x in obj if x is not None and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))]
    return obj

@app.after_request
def add_security_and_optimization_headers(response):
    # Mandatory CSP policy allowing OSM map tiles and CDN resources
    csp = (
        "default-src 'self' https://*.tile.openstreetmap.org https://cdnjs.cloudflare.com; "
        "script-src 'self' https://unpkg.com https://cdnjs.cloudflare.com; "
        "style-src 'self' https://fonts.googleapis.com https://unpkg.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com https://unpkg.com https://*.cartocdn.com; "
        "img-src 'self' data: blob: https://*.google.com https://*.gstatic.com https://*.duckduckgo.com https://*.clearbit.com https://*.cartocdn.com https://*.basemaps.cartocdn.com https://basemaps.cartocdn.com https://*.maplibre.org https://*.arcgisonline.com https://*.openstreetmap.org https://*.tile.openstreetmap.org; "
        "connect-src 'self' https://*.cartocdn.com https://*.basemaps.cartocdn.com https://basemaps.cartocdn.com https://*.maplibre.org https://*.arcgisonline.com https://*.openstreetmap.org https://*.tile.openstreetmap.org blob: data:; "
        "worker-src 'self' blob:; "
        "child-src 'self' blob:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'self';"
    )
    response.headers['Content-Security-Policy'] = csp
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # CORS support
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Accept, Accept-Encoding'
    
    # Ensure Vary: Accept-Encoding is present outside compression block
    vary = response.headers.get('Vary')
    if not vary:
        response.headers['Vary'] = 'Accept-Encoding'
    elif 'Accept-Encoding' not in vary:
        response.headers['Vary'] = f'{vary}, Accept-Encoding'

    # Attach Rate Limit headers from g if present
    if hasattr(g, 'rate_limit_limit'):
        response.headers.setdefault('X-RateLimit-Limit', str(g.rate_limit_limit))
        response.headers.setdefault('X-RateLimit-Remaining', str(g.rate_limit_remaining))

    # Attach Cache-Control: no-store on errors
    if response.status_code >= 400:
        response.headers['Cache-Control'] = 'no-store'
    
    # Gzip compression optimization
    accept_encoding = request.headers.get('Accept-Encoding', '').lower()
    wants_gzip = False
    if 'gzip' in accept_encoding:
        parts = [p.strip() for p in accept_encoding.split(',')]
        for p in parts:
            if p.startswith('gzip'):
                if 'q=0' in p and not ('q=0.' in p and p.split('q=')[1].strip('0.') != ''):
                    pass
                else:
                    wants_gzip = True
            elif p == '*' and not any(part.startswith('gzip') for part in parts):
                wants_gzip = True

    if (wants_gzip and 200 <= response.status_code < 300 
            and not response.direct_passthrough and 'Content-Encoding' not in response.headers):
        data = response.get_data()
        if len(data) >= 500:
            gzip_buffer = io.BytesIO()
            with gzip.GzipFile(mode='wb', fileobj=gzip_buffer) as gzip_file:
                gzip_file.write(data)
            compressed_data = gzip_buffer.getvalue()
            response.set_data(compressed_data)
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = str(len(compressed_data))
            
    return response

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/startups', methods=['GET'])
def get_startups():
    client_ip = request.remote_addr or "127.0.0.1"
    allowed, retry_after, remaining, limit_val = _check_rate_limit(client_ip)
    g.rate_limit_limit = limit_val
    g.rate_limit_remaining = 0 if not allowed else remaining
    if not allowed:
        resp = make_response(jsonify({"error": "Rate limit exceeded. Please try again later."}), 429)
        resp.headers['Retry-After'] = str(retry_after)
        return resp

    is_valid, err_msg = _validate_query_params(request.args)
    if not is_valid:
        return jsonify({"error": err_msg}), 400

    try:
        startups = load_startups()
        min_lat = _safe_float(request.args.get('min_lat'))
        max_lat = _safe_float(request.args.get('max_lat'))
        min_lng = _safe_float(request.args.get('min_lng'))
        max_lng = _safe_float(request.args.get('max_lng'))
        limit = request.args.get('limit', default=500, type=int)
        
        filtered = []
        for s in startups:
            lat = _safe_float(s.get("lat"))
            lng = _safe_float(s.get("lng"))
            if min_lat is not None and max_lat is not None and min_lng is not None and max_lng is not None:
                if s.get("has_pin") is False:
                    pass
                else:
                    eff_lat = lat if lat is not None else 12.9716
                    eff_lng = lng if lng is not None else 77.5946
                    if eff_lat < min_lat or eff_lat > max_lat or eff_lng < min_lng or eff_lng > max_lng:
                        continue
            filtered.append(s)
            
        filtered.sort(key=lambda x: len(x.get("job_openings") or []), reverse=True)
        if limit > 0:
            filtered = filtered[:limit]

        light_list = []
        for s in filtered:
            logo_domain = s.get("logo_domain", "")
            logo_url = f"https://www.google.com/s2/favicons?domain={logo_domain}&sz=128" if logo_domain else ""
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

            light_list.append({
                "id": s.get("id"),
                "name": _sanitize_string(s.get("name")),
                "lat": lat_val if (has_pin_val and lat_val is not None) else 12.9716,
                "lng": lng_val if (has_pin_val and lng_val is not None) else 77.5946,
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
            })
            
        lean_payload = _strip_redundant(light_list)
        resp = make_response(jsonify(lean_payload))
        resp.headers['Cache-Control'] = 'public, max-age=60'
        return resp
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/startups/<int:startup_id>', methods=['GET'])
def get_startup_details(startup_id):
    client_ip = request.remote_addr or "127.0.0.1"
    allowed, retry_after, remaining, limit_val = _check_rate_limit(client_ip)
    g.rate_limit_limit = limit_val
    g.rate_limit_remaining = 0 if not allowed else remaining
    if not allowed:
        resp = make_response(jsonify({"error": "Rate limit exceeded. Please try again later."}), 429)
        resp.headers['Retry-After'] = str(retry_after)
        return resp

    is_valid, err_msg = _validate_query_params(request.args)
    if not is_valid:
        return jsonify({"error": err_msg}), 400

    try:
        startups = load_startups()
        for s in startups:
            if s.get("id") == startup_id:
                s_copy = dict(s)
                for field in ["name", "city", "description", "industry", "funding_stage", "total_raised", "verified_email"]:
                    if field in s_copy:
                        s_copy[field] = _sanitize_string(s_copy[field])

                logo_domain = s_copy.get("logo_domain", "")
                s_copy["logo_url"] = f"https://www.google.com/s2/favicons?domain={logo_domain}&sz=128" if logo_domain else ""
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
                            "location": _sanitize_string(j.get("location", "Bengaluru")),
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

                lean_payload = _strip_redundant(s_copy)
                resp = make_response(jsonify(lean_payload))
                resp.headers['Cache-Control'] = 'public, max-age=60'
                return resp
        return jsonify({"error": "Startup not found"}), 404
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    # Servers MUST listen on localhost or 127.0.0.1 when testing. Servers MUST NOT listen on 0.0.0.0.
    app.run(debug=True, host='127.0.0.1', port=5001)
