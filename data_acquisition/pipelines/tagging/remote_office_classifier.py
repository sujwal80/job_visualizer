"""
Remote Office Classification Module

Calculates geographic Haversine distances between company coordinates and
canonical multi-city center coordinates to dynamically classify remote offices (`is_remote_office`).
Ensures floating-point safety against NaN and Infinity values.
"""

import math
import os

try:
    from geo_config import DEFAULT_TARGET_CITY, get_city_center_coordinates
except ImportError:
    from data_acquisition.geo_config import DEFAULT_TARGET_CITY, get_city_center_coordinates


def _get_threshold_km():
    try:
        return float(os.environ.get("REMOTE_OFFICE_DISTANCE_THRESHOLD_KM", "50.0"))
    except (ValueError, TypeError):
        return 50.0


# Default loaded value (inspectable via module attribute)
REMOTE_OFFICE_DISTANCE_THRESHOLD_KM = _get_threshold_km()


def _is_valid_float(val):
    if val is None:
        return False
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return False
        return True
    except (ValueError, TypeError):
        return False


def haversine_distance_km(lat1, lng1, lat2, lng2):
    """
    Calculate the great-circle distance between two points on Earth (in kilometers)
    using the Haversine formula (R = 6371.0 km).
    Returns None if any argument is None, NaN, or Infinity.
    """
    if not (_is_valid_float(lat1) and _is_valid_float(lng1) and _is_valid_float(lat2) and _is_valid_float(lng2)):
        return None

    lat1_f = float(lat1)
    lng1_f = float(lng1)
    lat2_f = float(lat2)
    lng2_f = float(lng2)

    R = 6371.0  # Earth radius in kilometers

    d_lat = math.radians(lat2_f - lat1_f)
    d_lng = math.radians(lng2_f - lng1_f)

    a = (math.sin(d_lat / 2.0) ** 2 +
         math.cos(math.radians(lat1_f)) * math.cos(math.radians(lat2_f)) * math.sin(d_lng / 2.0) ** 2)
    a = max(0.0, min(1.0, a))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    return R * c


def check_remote_office_status(company_record, target_city=None):
    """
    Dynamically classify whether a company record represents a remote office
    relative to target_city center coordinates (`MULTI_CITY_CENTERS`).

    Mutates `company_record` in place:
      - `is_remote_office` (bool)
      - `remote_office_distance_km` (float or None)
      - Appends `" (Remote Office)"` to `city` if remote and not already present.
    """
    if not isinstance(company_record, dict):
        return False

    # Ensure floating-point safety: sanitize NaN / Infinity coordinates to None
    lat = company_record.get("lat")
    lng = company_record.get("lng")
    if lat is not None and not _is_valid_float(lat):
        company_record["lat"] = None
        lat = None
    if lng is not None and not _is_valid_float(lng):
        company_record["lng"] = None
        lng = None

    effective_city = target_city if target_city is not None else DEFAULT_TARGET_CITY
    center = get_city_center_coordinates(effective_city)

    # If target is global/worldwide or no center coordinates exist
    if center is None:
        address_text = " ".join([
            str(company_record.get("office_address") or ""),
            str(company_record.get("city") or ""),
            str(company_record.get("location") or "")
        ]).lower()
        is_explicitly_remote = "remote" in address_text
        company_record["is_remote_office"] = bool(is_explicitly_remote)
        company_record["remote_office_distance_km"] = None
        return company_record["is_remote_office"]

    center_lat, center_lng = center
    threshold = _get_threshold_km()

    if _is_valid_float(lat) and _is_valid_float(lng):
        dist_km = haversine_distance_km(lat, lng, center_lat, center_lng)
        if dist_km is not None:
            if dist_km > threshold:
                company_record["is_remote_office"] = True
                company_record["remote_office_distance_km"] = round(dist_km, 2)
                city_str = str(company_record.get("city") or "").strip()
                if " (Remote Office)" not in city_str:
                    company_record["city"] = f"{city_str} (Remote Office)".strip() if city_str else "(Remote Office)"
            else:
                company_record["is_remote_office"] = False
                company_record["remote_office_distance_km"] = round(dist_km, 2)
                city_str = str(company_record.get("city") or "")
                if " (Remote Office)" in city_str:
                    company_record["city"] = city_str.replace(" (Remote Office)", "").strip()
            return company_record["is_remote_office"]

    # If coordinates are missing (None), fallback to explicit address check
    address_text = " ".join([
        str(company_record.get("office_address") or ""),
        str(company_record.get("city") or ""),
        str(company_record.get("location") or "")
    ]).lower()
    company_record["is_remote_office"] = "remote" in address_text
    company_record["remote_office_distance_km"] = None
    return company_record["is_remote_office"]
