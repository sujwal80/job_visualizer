from flask import Flask, jsonify, render_template, request, make_response, g
import json
import os
import time
import math
import gzip
import io
from collections import defaultdict
from werkzeug.middleware.proxy_fix import ProxyFix

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
    lat = s.get("lat")
    lng = s.get("lng")
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
            for s in data:
                s["has_pin"] = _check_has_pin(s)
                if "website" in s:
                    s["website"] = _sanitize_url(s.get("website"))
                if "url" in s:
                    s["url"] = _sanitize_url(s.get("url"))
                for f_obj in s.get("founders", []):
                    if isinstance(f_obj, dict) and "linkedin" in f_obj:
                        f_obj["linkedin"] = _sanitize_url(f_obj.get("linkedin"))
                for j_obj in s.get("job_openings", []):
                    if isinstance(j_obj, dict) and "url" in j_obj:
                        j_obj["url"] = _sanitize_url(j_obj.get("url"))
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
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
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
        return [_strip_redundant(x) for x in obj if x is not None]
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
        min_lat = request.args.get('min_lat', type=float)
        max_lat = request.args.get('max_lat', type=float)
        min_lng = request.args.get('min_lng', type=float)
        max_lng = request.args.get('max_lng', type=float)
        limit = request.args.get('limit', default=500, type=int)
        
        filtered = []
        for s in startups:
            lat = s.get("lat")
            lng = s.get("lng")
            if min_lat is not None and max_lat is not None and min_lng is not None and max_lng is not None:
                if s.get("has_pin") is False:
                    pass
                else:
                    eff_lat = lat if lat is not None else 12.9716
                    eff_lng = lng if lng is not None else 77.5946
                    if eff_lat < min_lat or eff_lat > max_lat or eff_lng < min_lng or eff_lng > max_lng:
                        continue
            filtered.append(s)
            
        filtered.sort(key=lambda x: len(x.get("job_openings", [])), reverse=True)
        if limit > 0:
            filtered = filtered[:limit]

        light_list = []
        for s in filtered:
            logo_domain = s.get("logo_domain", "")
            logo_url = f"https://www.google.com/s2/favicons?domain={logo_domain}&sz=128" if logo_domain else ""
            website = _sanitize_url(s.get("website", ""))
            
            job_openings = s.get("job_openings", [])
            experiences = list({j.get("experience") for j in job_openings if isinstance(j, dict) and j.get("experience") and j.get("experience") != "Not specified"})
            salaries = list({j.get("salary") for j in job_openings if isinstance(j, dict) and j.get("salary") and j.get("salary") != "Not disclosed"})
            job_types = list({j.get("job_type") for j in job_openings if isinstance(j, dict) and j.get("job_type")})
            all_skills = set()
            for j in job_openings:
                if isinstance(j, dict) and isinstance(j.get("skills"), list):
                    all_skills.update(j.get("skills"))
            skills = list(all_skills)

            light_list.append({
                "id": s.get("id"),
                "name": s.get("name", ""),
                "lat": s.get("lat") if s.get("has_pin") else 12.9716,
                "lng": s.get("lng") if s.get("has_pin") else 77.5946,
                "city": s.get("city", ""),
                "experience": experiences,
                "salary": salaries,
                "job_type": job_types,
                "skills": skills,
                "logo_url": logo_url,
                "url": website,
                "description": s.get("description", "")[:120],
                "has_pin": s.get("has_pin", True),
                "industry": s.get("industry"),
                "head_count": s.get("head_count"),
                "logo_domain": logo_domain,
                "website": website,
                "funding_stage": s.get("funding_stage", "Seed / Active"),
                "total_raised": s.get("total_raised", "Undisclosed"),
                "is_active_website": s.get("is_active_website", True),
                "verified_email": s.get("verified_email", ""),
                "job_count": len(job_openings),
                "job_titles": [j.get("title", "") for j in job_openings if isinstance(j, dict)],
                "founder_names": [f.get("name", "") for f in s.get("founders", []) if isinstance(f, dict)]
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

    try:
        startups = load_startups()
        for s in startups:
            if s.get("id") == startup_id:
                s_copy = dict(s)
                logo_domain = s_copy.get("logo_domain", "")
                s_copy["logo_url"] = f"https://www.google.com/s2/favicons?domain={logo_domain}&sz=128" if logo_domain else ""
                s_copy["url"] = _sanitize_url(s_copy.get("website", ""))
                if "website" in s_copy:
                    s_copy["website"] = _sanitize_url(s_copy.get("website", ""))
                
                job_openings = s_copy.pop("job_openings", [])
                clean_jobs = []
                for j in job_openings:
                    if isinstance(j, dict):
                        clean_jobs.append({
                            "title": j.get("title", ""),
                            "url": _sanitize_url(j.get("url", "")),
                            "department": j.get("department", "General"),
                            "experience": j.get("experience", ""),
                            "salary": j.get("salary", ""),
                            "job_type": j.get("job_type", ""),
                            "skills": j.get("skills", []),
                            "location": j.get("location", "Bengaluru"),
                            "posted_date": j.get("posted_date", "Active"),
                            "source": j.get("source", "Direct")
                        })
                s_copy["jobs"] = clean_jobs
                s_copy["job_count"] = len(clean_jobs)

                s_copy["experience"] = list({j.get("experience") for j in clean_jobs if j.get("experience") and j.get("experience") != "Not specified"})
                s_copy["salary"] = list({j.get("salary") for j in clean_jobs if j.get("salary") and j.get("salary") != "Not disclosed"})
                s_copy["job_type"] = list({j.get("job_type") for j in clean_jobs if j.get("job_type")})
                all_skills = set()
                for j in clean_jobs:
                    if isinstance(j.get("skills"), list):
                        all_skills.update(j.get("skills"))
                s_copy["skills"] = list(all_skills)

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
        if not allowed:
            resp = make_response(jsonify({"error": "Rate limit exceeded"}), 429)
            resp.headers['Retry-After'] = str(retry_after)
            return resp
        return jsonify({"error": "Unauthorized"}), 401

    uid = user.get("user_id")
    if not uid or str(uid).strip() in ["", "unknown", "None"]:
        key = f"ip_{request.remote_addr}"
        is_user_bucket = False
    else:
        key = str(uid)
        is_user_bucket = True
    allowed, retry_after, remaining, limit_val, reset_time = _check_rate_limit(key, is_user=is_user_bucket)
    g.rate_limit_limit = limit_val
    g.rate_limit_remaining = 0 if not allowed else remaining
    g.rate_limit_reset = reset_time
    if not allowed:
        resp = make_response(jsonify({"error": "Rate limit exceeded"}), 429)
        resp.headers['Retry-After'] = str(retry_after)
        return resp

    if len(request.args) > 0:
        return jsonify({"error": "Query parameters are not supported on startup detail endpoint"}), 400

    try:
        startups = load_startups()
        for s in startups:
            if s.get("id") == startup_id:
                s_copy = dict(s)
                s_copy["name"] = _sanitize_text(s_copy.get("name", ""))
                s_copy["city"] = _sanitize_text(s_copy.get("city", ""))
                s_copy["description"] = _sanitize_text(s_copy.get("description", ""))
                s_copy["industry"] = _sanitize_text(s_copy.get("industry"))
                s_copy["funding_stage"] = _sanitize_text(s_copy.get("funding_stage", "Seed / Active"))
                s_copy["total_raised"] = _sanitize_text(s_copy.get("total_raised", "Undisclosed"))
                s_copy["verified_email"] = _sanitize_text(s_copy.get("verified_email", ""))
                logo_domain = _sanitize_domain(s_copy.get("logo_domain", ""))
                if logo_domain:
                    clean_domain = urllib.parse.quote(logo_domain.strip(), safe='.-_')
                    s_copy["logo_url"] = f"https://www.google.com/s2/favicons?domain={clean_domain}&sz=128"
                else:
                    s_copy["logo_url"] = ""
                s_copy["url"] = _sanitize_url(s_copy.get("website", ""))
                if "website" in s_copy:
                    s_copy["website"] = _sanitize_url(s_copy.get("website", ""))
                if "founders" in s_copy and isinstance(s_copy["founders"], list):
                    clean_founders = []
                    for f in s_copy["founders"]:
                        if isinstance(f, dict):
                            f_copy = dict(f)
                            if "linkedin" in f_copy:
                                f_copy["linkedin"] = _sanitize_url(f_copy.get("linkedin"))
                            clean_founders.append(f_copy)
                        else:
                            clean_founders.append(f)
                    s_copy["founders"] = clean_founders
                
                job_openings = s_copy.pop("job_openings", [])
                clean_jobs = []
                for j in job_openings:
                    if isinstance(j, dict):
                        clean_jobs.append({
                            "title": j.get("title", ""),
                            "url": _sanitize_url(j.get("url", "")),
                            "department": j.get("department", "General"),
                            "experience": j.get("experience", ""),
                            "salary": j.get("salary", ""),
                            "job_type": j.get("job_type", ""),
                            "skills": j.get("skills", []),
                            "location": j.get("location", "Bengaluru"),
                            "posted_date": j.get("posted_date", "Active"),
                            "source": j.get("source", "Direct")
                        })
                s_copy["jobs"] = clean_jobs
                s_copy["job_count"] = len(clean_jobs)

                s_copy["experience"] = list({j.get("experience") for j in clean_jobs if j.get("experience") and j.get("experience") != "Not specified"})
                s_copy["salary"] = list({j.get("salary") for j in clean_jobs if j.get("salary") and j.get("salary") != "Not disclosed"})
                s_copy["job_type"] = list({j.get("job_type") for j in clean_jobs if j.get("job_type")})
                all_skills = set()
                for j in clean_jobs:
                    if isinstance(j.get("skills"), list):
                        all_skills.update(j.get("skills"))
                s_copy["skills"] = list(all_skills)

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
