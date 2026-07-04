import re
import math

REQUIRED_FIELDS = {
    'id', 'name', 'lat', 'lng', 'city', 'experience', 
    'salary', 'job_type', 'skills', 'logo_url', 'url', 'description'
}

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
