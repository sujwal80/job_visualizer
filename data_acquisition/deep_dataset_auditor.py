#!/usr/bin/env python3
"""
Deep Dataset Auditor & Verification Tool
Path: data_acquisition/deep_dataset_auditor.py

Executes parallel HTTP & geographic verification across all 367 startups
and 2,462 job openings in backend/startups.json:
 1. Logo URL Image Verification (HTTP 200, Content-Type, Non-404/Placeholder)
 2. Job Link Validity & Expiration Check (HTTP status, Expiration Phrases, Auth Traps)
 3. Location & Geocode Coordinate Verification (Lat/Lng bounds, City Geofencing)
"""

import os
import sys
import json
import re
import urllib.parse
import concurrent.futures
import requests
import socket
import logging

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.utils.validation import safe_http_request, is_safe_svg, is_parking_page, resolve_and_verify_host, is_blacklisted_domain
from data_acquisition.geo_config import MULTI_CITY_CENTERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DeepAuditor")

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
}

EXPIRED_PHRASES = [
    "no longer accepting applications",
    "job is closed",
    "position has been filled",
    "job expired",
    "posting is no longer available",
    "this job is no longer active",
    "job not found",
    "position is closed",
    "no longer hiring",
    "applications closed",
    "job closed",
    "this role is closed"
]


def verify_single_logo(startup):
    """
    Verify logo URL validity for a startup record.
    Returns dict with verification results.
    """
    sid = startup.get("id")
    name = startup.get("name", "Unknown")
    logo_url = str(startup.get("logo_svg_url") or "").strip()

    if not logo_url:
        return {
            "id": sid,
            "name": name,
            "logo_url": "",
            "status": "EMPTY",
            "is_valid": True,
            "reason": "No logo provided (renders initials avatar in UI)"
        }

    if not logo_url.startswith(("http://", "https://")):
        return {
            "id": sid,
            "name": name,
            "logo_url": logo_url,
            "status": "INVALID_URL",
            "is_valid": False,
            "reason": "URL does not start with http:// or https://"
        }

    if is_blacklisted_domain(logo_url):
        return {
            "id": sid,
            "name": name,
            "logo_url": logo_url,
            "status": "BLACKLISTED",
            "is_valid": False,
            "reason": "Logo URL hosted on blacklisted aggregator/shortener domain"
        }

    try:
        res = safe_http_request("GET", logo_url, headers=DEFAULT_HEADERS, timeout=6, stream=True)
        if res.status_code != 200:
            return {
                "id": sid,
                "name": name,
                "logo_url": logo_url,
                "status": f"HTTP_{res.status_code}",
                "is_valid": False,
                "reason": f"HTTP status {res.status_code}"
            }

        c_type = res.headers.get("Content-Type", "").lower()
        chunk = res.raw.read(4096)
        if not chunk:
            return {
                "id": sid,
                "name": name,
                "logo_url": logo_url,
                "status": "EMPTY_RESPONSE",
                "is_valid": False,
                "reason": "Empty HTTP response body"
            }

        # Check Unavatar error fallback header
        if res.headers.get("x-unavatar-fallback") == "true":
            return {
                "id": sid,
                "name": name,
                "logo_url": logo_url,
                "status": "UNAVATAR_FALLBACK",
                "is_valid": False,
                "reason": "Unavatar default 404 fallback response"
            }

        chunk_str = chunk.decode("utf-8", errors="ignore").lower()
        is_svg = "svg" in c_type or "<svg" in chunk_str or "<?xml" in chunk_str
        is_html = "text/html" in c_type or "<html" in chunk_str or "<!doctype html" in chunk_str

        if is_html:
            return {
                "id": sid,
                "name": name,
                "logo_url": logo_url,
                "status": "HTML_ERROR_PAGE",
                "is_valid": False,
                "reason": "URL returned HTML error page instead of image"
            }

        if is_svg:
            remaining = res.raw.read(1024 * 1024)
            full_content = chunk + remaining
            if not is_safe_svg(full_content):
                return {
                    "id": sid,
                    "name": name,
                    "logo_url": logo_url,
                    "status": "UNSAFE_SVG",
                    "is_valid": False,
                    "reason": "SVG failed security validation (script or DTD injection)"
                }

        return {
            "id": sid,
            "name": name,
            "logo_url": logo_url,
            "status": "VALID",
            "is_valid": True,
            "reason": f"Valid image ({c_type.split(';')[0]})"
        }

    except Exception as e:
        return {
            "id": sid,
            "name": name,
            "logo_url": logo_url,
            "status": "CONNECTION_ERROR",
            "is_valid": False,
            "reason": f"Network exception: {str(e)[:60]}"
        }


def verify_single_job(task):
    """
    Verify job opening URL validity and expiration status.
    Returns dict with verification results.
    """
    sid, comp_name, job = task
    title = str(job.get("title") or "Unknown Role").strip()
    url = str(job.get("url") or job.get("job_url") or "").strip()

    if not url or not url.startswith(("http://", "https://")):
        return {
            "company_id": sid,
            "company_name": comp_name,
            "title": title,
            "url": url,
            "status": "INVALID_URL",
            "is_valid": False,
            "reason": "Missing or malformed job URL"
        }

    try:
        res = safe_http_request("GET", url, headers=DEFAULT_HEADERS, timeout=6)
        
        # 1. Status Code Inspection
        if res.status_code in [404, 410]:
            return {
                "company_id": sid,
                "company_name": comp_name,
                "title": title,
                "url": url,
                "status": f"HTTP_{res.status_code}",
                "is_valid": False,
                "reason": f"Job URL returned HTTP {res.status_code} (Not Found/Gone)"
            }

        if res.status_code in [403, 429, 503]:
            # Cloudflare or rate-limited endpoints are considered active/protected
            return {
                "company_id": sid,
                "company_name": comp_name,
                "title": title,
                "url": url,
                "status": f"HTTP_{res.status_code}_PROTECTED",
                "is_valid": True,
                "reason": f"HTTP {res.status_code} (Cloudflare / Rate Limit Protected - Preserved Active)"
            }

        # 2. Redirect to Auth / Login Traps
        final_url = res.url.lower() if hasattr(res, "url") and res.url else url.lower()
        if "login" in final_url or "session_redirect" in final_url:
            return {
                "company_id": sid,
                "company_name": comp_name,
                "title": title,
                "url": url,
                "status": "AUTH_REDIRECT_TRAP",
                "is_valid": False,
                "reason": "Redirected to login/authentication portal"
            }

        # 3. Parking Page Check
        if is_parking_page(res.text, len(res.content)):
            return {
                "company_id": sid,
                "company_name": comp_name,
                "title": title,
                "url": url,
                "status": "PARKING_PAGE",
                "is_valid": False,
                "reason": "Domain parking page detected"
            }

        # 4. Text Expiration Phrases
        text_lower = res.text.lower()
        for phrase in EXPIRED_PHRASES:
            if phrase in text_lower:
                return {
                    "company_id": sid,
                    "company_name": comp_name,
                    "title": title,
                    "url": url,
                    "status": "EXPIRED_PHRASE",
                    "is_valid": False,
                    "reason": f"Matched expiration phrase: '{phrase}'"
                }

        return {
            "company_id": sid,
            "company_name": comp_name,
            "title": title,
            "url": url,
            "status": "ACTIVE_200",
            "is_valid": True,
            "reason": "HTTP 200 OK (Job page active)"
        }

    except Exception as e:
        # Network timeout / connection error assumes active to prevent false-positive pruning
        return {
            "company_id": sid,
            "company_name": comp_name,
            "title": title,
            "url": url,
            "status": "NETWORK_TIMEOUT",
            "is_valid": True,
            "reason": f"Transient network timeout ({type(e).__name__}) - Preserved Active"
        }


def verify_single_location(startup):
    """
    Verify location string and geocode coordinates for a startup.
    Returns dict with verification results.
    """
    sid = startup.get("id")
    name = startup.get("name", "Unknown")
    city = str(startup.get("city") or "").strip()
    lat = startup.get("lat")
    lng = startup.get("lng")
    has_pin = startup.get("has_pin", True)

    if lat is None or lng is None:
        return {
            "id": sid,
            "name": name,
            "city": city,
            "lat": lat,
            "lng": lng,
            "status": "UNPINNED_REMOTE",
            "is_valid": True,
            "reason": "Remote office / unpinned hub (has_pin=False)"
        }

    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (ValueError, TypeError):
        return {
            "id": sid,
            "name": name,
            "city": city,
            "lat": lat,
            "lng": lng,
            "status": "INVALID_COORDS",
            "is_valid": False,
            "reason": f"Invalid non-numeric coordinates: ({lat}, {lng})"
        }

    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lng_f <= 180.0):
        return {
            "id": sid,
            "name": name,
            "city": city,
            "lat": lat_f,
            "lng": lng_f,
            "status": "OUT_OF_BOUNDS",
            "is_valid": False,
            "reason": f"Coordinates out of world bounds: ({lat_f}, {lng_f})"
        }

    # Geofence city check for major Indian hubs if city name matches
    city_lower = city.lower()
    matched_city = None
    for c_key in ["bengaluru", "bangalore", "mumbai", "hyderabad", "delhi", "gurugram", "noida", "pune", "chennai"]:
        if c_key in city_lower:
            matched_city = c_key
            break

    if matched_city:
        expected_lat, expected_lng = MULTI_CITY_CENTERS.get(matched_city, (None, None))
        if expected_lat and expected_lng:
            # Check within 1.5 degrees (~150km) of city center
            delta_lat = abs(lat_f - expected_lat)
            delta_lng = abs(lng_f - expected_lng)
            if delta_lat > 1.5 or delta_lng > 1.5:
                return {
                    "id": sid,
                    "name": name,
                    "city": city,
                    "lat": lat_f,
                    "lng": lng_f,
                    "status": "MISMATCHED_GEOFENCE",
                    "is_valid": False,
                    "reason": f"Coordinates ({lat_f:.4f}, {lng_f:.4f}) deviate >150km from claimed city '{city}'"
                }

    return {
        "id": sid,
        "name": name,
        "city": city,
        "lat": lat_f,
        "lng": lng_f,
        "status": "VALID_GEOCODE",
        "is_valid": True,
        "reason": f"Valid coordinates ({lat_f:.4f}, {lng_f:.4f}) matching '{city}'"
    }


def run_deep_audit(db_path="backend/startups.json", max_workers=20):
    if not os.path.isabs(db_path):
        db_path = os.path.join(PROJECT_ROOT, db_path)

    with open(db_path, "r", encoding="utf-8") as f:
        startups = json.load(f)

    print("=========================================================================")
    print("      DEEP DATASET AUDITOR: LOGOS, JOB LINKS & GEOLOCATION VERIFICATION  ")
    print("=========================================================================")
    print(f" Target Dataset : {db_path}")
    print(f" Total Startups : {len(startups)}")

    job_tasks = []
    for s in startups:
        sid = s.get("id")
        comp_name = s.get("name", "Unknown")
        for j in s.get("job_openings", []):
            job_tasks.append((sid, comp_name, dict(j)))

    print(f" Total Job Links: {len(job_tasks)}")
    print("-------------------------------------------------------------------------\n")

    # 1. Audit Locations & Geocodes
    print("[Phase 1/3] Auditing Location Strings & Geocode Coordinates...")
    loc_results = [verify_single_location(s) for s in startups]
    invalid_locs = [r for r in loc_results if not r["is_valid"]]
    print(f" -> Geocode Audit Complete: {len(startups) - len(invalid_locs)} / {len(startups)} Valid ({len(invalid_locs)} Issues Detected)\n")

    # 2. Audit Logo Image URLs
    print("[Phase 2/3] Auditing Logo URLs (HTTP 200, Content-Type, Safety)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        logo_results = list(executor.map(verify_single_logo, startups))
    invalid_logos = [r for r in logo_results if not r["is_valid"]]
    print(f" -> Logo Audit Complete: {len(startups) - len(invalid_logos)} / {len(startups)} Valid ({len(invalid_logos)} Issues Detected)\n")

    # 3. Audit Job Posting Links
    print("[Phase 3/3] Auditing Job Posting URLs (HTTP Status, Apply Mechanisms, Expiration)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        job_results = list(executor.map(verify_single_job, job_tasks))
    invalid_jobs = [r for r in job_results if not r["is_valid"]]
    print(f" -> Job Link Audit Complete: {len(job_tasks) - len(invalid_jobs)} / {len(job_tasks)} Valid ({len(invalid_jobs)} Issues Detected)\n")

    print("=========================================================================")
    print("                    DEEP AUDIT FINAL REPORT SUMMARY                       ")
    print("=========================================================================")
    print(f" Startups Audited      : {len(startups)}")
    print(f" Geocode Locations     : {len(startups) - len(invalid_locs)} Valid | {len(invalid_locs)} Invalid")
    print(f" Logo Image URLs       : {len(startups) - len(invalid_logos)} Valid | {len(invalid_logos)} Invalid")
    print(f" Job Posting Links     : {len(job_tasks) - len(invalid_jobs)} Valid | {len(invalid_jobs)} Invalid")
    print("=========================================================================\n")

    report = {
        "total_startups": len(startups),
        "total_jobs": len(job_tasks),
        "location_audit": {
            "valid_count": len(startups) - len(invalid_locs),
            "invalid_count": len(invalid_locs),
            "issues": invalid_locs
        },
        "logo_audit": {
            "valid_count": len(startups) - len(invalid_logos),
            "invalid_count": len(invalid_logos),
            "issues": invalid_logos
        },
        "job_link_audit": {
            "valid_count": len(job_tasks) - len(invalid_jobs),
            "invalid_count": len(invalid_jobs),
            "issues": invalid_jobs
        }
    }

    return report


if __name__ == "__main__":
    report = run_deep_audit()
    with open("deep_audit_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("Full audit report written to 'deep_audit_report.json'.")
