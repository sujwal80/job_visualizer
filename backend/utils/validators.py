"""
Validation and Sanitization Utilities
Houses security hardening helper functions for string cleaning, URL sanitization,
query parameter inspection, floating-point validation, and payload pruning.
"""

import re
import math

try:
    from backend.config import FALLBACK_COORDINATES, PIN_DELTA_THRESHOLD, GENERIC_HUB_LABELS
except ImportError:
    from config import FALLBACK_COORDINATES, PIN_DELTA_THRESHOLD, GENERIC_HUB_LABELS

# Essential fields that must never be stripped from startup payload objects during serialization.
REQUIRED_FIELDS = {
    'id', 'name', 'lat', 'lng', 'city', 'experience', 
    'salary', 'job_type', 'skills', 'logo_url', 'url', 'description'
}

def _sanitize_string(val):
    """
    Sanitize raw text strings by stripping HTML tags recursively, brackets, and null bytes.

    Args:
        val: The input value to sanitize (typically a string, int, or None).

    Returns:
        str: A stripped, safe string representation with HTML tags and null bytes removed.
    """
    if val is None:
        return ""
    if not isinstance(val, str):
        return val
    prev = ""
    while prev != val:
        prev = val
        val = re.sub(r'<[^<>]*>', '', val)
    # Remove leftover brackets and null bytes that could be used in bypass attacks
    val = val.replace('<', '').replace('>', '').replace('\x00', '')
    return val.strip()

def _safe_float(val, default=None):
    """
    Safely parse a numeric float from an input value, handling NaN and Infinity.

    Args:
        val: The raw value to convert to float.
        default: The default fallback value if conversion fails or if NaN/Inf is encountered.

    Returns:
        float or None: The parsed float value, or the default fallback.
    """
    if val is None:
        return default
    try:
        f = float(val)
        # Check for boundary IEEE 754 floating-point exceptions (NaN and Infinity)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default

def _check_has_pin(s):
    """
    Determine if a startup dictionary has specific street/hub level GPS coordinates.

    Generic Bangalore city-level coordinates (or city-only names) return False so they
    can be grouped into general regional clusters or hub listings.

    Args:
        s (dict): The startup dictionary containing coordinate and address metadata.

    Returns:
        bool: True if specific coordinates are present, False if unpinned or general city hub.
    """
    if s.get("is_remote_office") is True:
        return False
    lat = _safe_float(s.get("lat"))
    lng = _safe_float(s.get("lng"))
    if lat is None or lng is None:
        return False
    # Check if coordinates match default generic city centers within delta threshold
    for f_lat, f_lng in FALLBACK_COORDINATES:
        if abs(lat - f_lat) < PIN_DELTA_THRESHOLD and abs(lng - f_lng) < PIN_DELTA_THRESHOLD:
            return False
    addr = str(s.get("address") or s.get("street_address") or s.get("bangalore_address") or s.get("city") or "").strip().lower()
    # Treat general city names without a specific street address as unpinned
    if addr in GENERIC_HUB_LABELS:
        return False
    return True

def _sanitize_url(url):
    """
    Sanitize URLs against Cross-Site Scripting (XSS) and dangerous protocol schemes.

    Strips zero-width control characters and checks against dangerous schemes both
    in raw text and after URL/HTML entity decoding.

    Args:
        url (str): The raw URL string to sanitize.

    Returns:
        str: The sanitized URL string, or an empty string if a dangerous scheme is detected.
    """
    if not url or not isinstance(url, str):
        return ""
    url_clean = url.strip()
    # Strip zero-width spaces, directionality formatting, and control characters
    lower = re.sub(r'[\x00-\x20\x7f\u200b-\u200f\u2028\u2029\ufeff]', '', url_clean).lower()
    dangerous_schemes = ("javascript:", "data:", "vbscript:", "file:", "about:", "blob:", "view-source:", "mhtml:")
    if any(lower.startswith(scheme) for scheme in dangerous_schemes):
        return ""
    # Check against hex/decimal HTML entity encoded scheme bypasses (e.g. &#58; for colon)
    decoded_lower = lower.replace("&#58;", ":").replace("%3a", ":").replace("&#x3a;", ":").replace("&colon;", ":")
    if any(decoded_lower.startswith(scheme) for scheme in dangerous_schemes):
        return ""
    return url_clean

def _validate_query_params(args):
    """
    Validate incoming HTTP GET query parameters against flooding, SQLi, and XSS injection attempts.

    Args:
        args (MultiDict): The Werkzeug request.args dictionary of incoming query parameters.

    Returns:
        tuple: (bool valid, str error_message). If valid is True, error_message is None.
    """
    allowed_params = {'min_lat', 'max_lat', 'min_lng', 'max_lng', 'limit', 'city', 'skill', 'industry', 'search', 'dept', 'experience', 'exp', 'has_jobs'}
    
    # Prevent parameter flooding attacks by capping total parameter values across all keys
    total_params = sum(len(args.getlist(k)) for k in args.keys())
    if total_params > 20:
        return False, "Parameter flooding detected: total parameter values exceed maximum limit of 20"
        
    for key in args.keys():
        if key not in allowed_params:
            return False, f"Unsupported query parameter: '{key}'"
        vals = args.getlist(key)
        # Restrict duplicate parameter collisions for a single key to 5 values
        if len(vals) > 5:
            return False, f"Parameter flooding detected: too many duplicate values for parameter '{key}'"
        for val in vals:
            if len(val) > 100:
                return False, f"Parameter '{key}' exceeds maximum length of 100"
            lower = val.lower()
            # Inspect for XSS characters and common SQL injection keyword patterns
            if any(char in val for char in ["<", ">", "'", '"', ";", "--", "/*", "*/", "\x00"]) or \
               any(kw in lower for kw in ["javascript:", "data:", "vbscript:", "union select", "drop table", "insert into", "delete from", "update ", "exec(", "execute(", "or 1=1", "or true"]):
                return False, f"Parameter '{key}' contains invalid characters or injection attempts"

    # Validate coordinate bounding box numeric float ranges
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
    
    # Validate result limit parameter range [0, 5000]
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
    """
    Recursively clean data payloads by replacing None values with empty strings,
    pruning empty nested collections, and neutralizing IEEE 754 NaN/Infinity floats.

    This prevents frontend JavaScript from throwing TypeErrors or displaying 'undefined' text
    when rendering DOM elements.

    Args:
        obj: The data structure (dict, list, float, or scalar) to sanitize.

    Returns:
        The cleaned data structure suitable for lean JSON serialization.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    elif isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                v = 0.0 if k in ('lat', 'lng') else None
            # Preserve required schema keys even if empty
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
