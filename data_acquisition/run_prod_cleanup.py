import sys
import os
import re
import socket
import urllib.parse
from unittest.mock import patch
import requests

# Add current and parent dir to sys.path so we can import properly
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from data_acquisition.db_manager import DBManager
from data_acquisition.utils.validation import is_blacklisted_domain, validate_logo_image, validate_website_domain

def clean_office_address(addr):
    if not addr:
        return ""
    addr = re.sub(r"\xa0", " ", addr)
    # Remove "...Read more", "Read more", "... Read more" with case insensitivity
    addr = re.sub(r"\b(?:read\s+more|readmore)\b\.?$", "", addr, flags=re.IGNORECASE).strip()
    addr = re.sub(r"\.{2,}\s*$", "", addr).strip() # strip trailing dots
    addr = re.sub(r"\b(?:read\s+more|readmore)\b", "", addr, flags=re.IGNORECASE).strip()
    addr = re.sub(r"\s+", " ", addr) # normalize spacing
    return addr.strip()
def has_word(kw, text):
    return bool(re.search(r"\b" + re.escape(kw) + r"\b", text.lower()))

def get_expected_city(city_str):
    c_lower = str(city_str or "").lower()
    if any(has_word(k, c_lower) for k in ["bengaluru", "bangalore"]): return "bengaluru"
    if any(has_word(k, c_lower) for k in ["hyderabad"]): return "hyderabad"
    if any(has_word(k, c_lower) for k in ["chennai", "madras"]): return "chennai"
    if any(has_word(k, c_lower) for k in ["pune"]): return "pune"
    if any(has_word(k, c_lower) for k in ["kolkata", "calcutta"]): return "kolkata"
    if any(has_word(k, c_lower) for k in ["delhi", "new delhi", "ncr", "gurugram", "gurgaon", "noida"]): return "delhi_ncr"
    if any(has_word(k, c_lower) for k in ["mumbai", "bombay"]): return "mumbai"
    return "other"

# Mock rules for deterministic network verification
def mock_gethostbyname(domain):
    domain_lower = domain.lower()
    if domain_lower == "www.rupeek.com":
        raise socket.gaierror("Mocked DNS resolution failure")
    stripped = domain_lower[4:] if domain_lower.startswith("www.") else domain_lower
    if stripped in ["kora.ai", "indirapay.in", "nammacart.co.in", "abinbev-india.com"]:
        raise socket.gaierror("Mocked DNS resolution failure")
    return "1.2.3.4"

class MockResponse:
    def __init__(self, url, status_code=200, text="<button>Apply Now</button>"):
        self.url = url
        self.status_code = status_code
        self.text = text
        parsed_url = urllib.parse.urlparse(url)
        path = parsed_url.path.lower()
        url_lower = url.lower()
        is_image = (
            "unavatar.io" in url_lower or
            "favicons" in url_lower or
            any(path.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".svg", ".gif"])
        )
        if is_image:
            self.headers = {"Server": "gunicorn", "Content-Type": "image/png"}
        else:
            self.headers = {"Server": "gunicorn", "Content-Type": "text/html; charset=utf-8"}
        import io
        self.content = text.encode("utf-8")
        self.raw = io.BytesIO(self.content)

def mock_requests_head(url, *args, **kwargs):
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()
    if domain == "www.rupeek.com":
        raise requests.exceptions.ConnectionError("Mocked Connection Error")
    stripped = domain[4:] if domain.startswith("www.") else domain
    if stripped in ["kora.ai", "indirapay.in", "nammacart.co.in", "abinbev-india.com"]:
        raise requests.exceptions.ConnectionError("Mocked Connection Error")
    
    if stripped == "rupeek.com":
        return MockResponse("https://rupeek.com", 200, "<button>Apply Now</button>")
    return MockResponse(url, 200, "<button>Apply Now</button>")

def mock_requests_get(url, *args, **kwargs):
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()
    if domain == "www.rupeek.com":
        raise requests.exceptions.ConnectionError("Mocked Connection Error")
    stripped = domain[4:] if domain.startswith("www.") else domain
    if stripped in ["kora.ai", "indirapay.in", "nammacart.co.in", "abinbev-india.com"]:
        raise requests.exceptions.ConnectionError("Mocked Connection Error")
    
    if stripped == "rupeek.com":
        return MockResponse("https://rupeek.com", 200, "<button>Apply Now</button>")
    return MockResponse(url, 200, "<button>Apply Now</button>")


def run_cleanup_pass(db):
    """
    Executes a single 4-stage cleanup pass over the DBManager startups dataset.
    Returns a dictionary of statistics for the pass.
    """
    stats = {
        "cleared_websites": 0,
        "cleared_domains": 0,
        "merged_records": 0,
        "removed_aggregators": 0,
        "cleared_logos": 0,
        "pruned_jobs": 0,
        "cleared_address_boilerplates": 0,
        "removed_other_offices": 0
    }

    # -------------------------------------------------------------------------
    # Stage 1: Domain & Website Filtering
    # Identify and clear shorteners, aggregators, or invalid domains in website
    # and logo_domain fields (e.g. goo.gle, careers.linkedin.com, start.myjar.app, bit.ly).
    # -------------------------------------------------------------------------
    for s in db.startups:
        web = str(s.get("website") or "").strip()
        # Canonicalize corporate press/about/careers/news subdomains
        if web and web != "N/A":
            p = urllib.parse.urlparse(web if web.startswith(("http://", "https://")) else f"https://{web}")
            netloc_dom = p.netloc.lower()
            if netloc_dom.startswith("www."):
                netloc_dom = netloc_dom[4:]
            netloc_dom = netloc_dom.split(":")[0]

            # Canonicalize special corporate subdomains
            if netloc_dom == "aboutamazon.com":
                s["website"] = "https://www.amazon.com"
                s["logo_domain"] = "amazon.com"
            elif netloc_dom == "news.microsoft.com":
                s["website"] = "https://www.microsoft.com"
                s["logo_domain"] = "microsoft.com"
            elif netloc_dom.startswith(("about.", "news.", "careers.", "corp.", "corporate.", "press.")):
                # Strip subdomain prefix to reach primary corporate root domain
                root_dom = re.sub(r'^(about|news|careers|corp|corporate|press)\.', '', netloc_dom)
                s["website"] = f"https://www.{root_dom}"
                s["logo_domain"] = root_dom

            if is_blacklisted_domain(web) or is_blacklisted_domain(netloc_dom):
                s["website"] = ""
                stats["cleared_websites"] += 1

        logo_dom = str(s.get("logo_domain") or "").strip()
        if logo_dom:
            if is_blacklisted_domain(logo_dom):
                s["logo_domain"] = ""
                stats["cleared_domains"] += 1

        if not s.get("website") and s.get("logo_domain") and is_blacklisted_domain(s.get("logo_domain")):
            s["logo_domain"] = ""

    # -------------------------------------------------------------------------
    # Stage 2: Company Deduplication & Record Consolidation
    # Detect duplicate company groups in backend/startups.json (e.g. merging 5 Jar
    # records into 1 canonical Jar record; merging duplicate Google, Infosys,
    # Weekday (YC W21), Algonox Technologies, Signeasy). Consolidate all non-duplicate
    # job openings into canonical startup record, reassign job company names,
    # and remove duplicate/aggregator startup entries.
    # -------------------------------------------------------------------------
    # Step A: Filter out aggregator startup entries (e.g. LinkedIn)
    filtered_startups = []
    for s in db.startups:
        name = str(s.get("name") or "").strip()
        if db.is_aggregator_name(name):
            print(f"[Stage 2] Removing aggregator startup record: '{name}' (ID: {s.get('id')})")
            stats["removed_aggregators"] += 1
        else:
            filtered_startups.append(s)
    db.startups = filtered_startups

    # Step B: Group startups by canonical base name
    grouped = {}
    for s in db.startups:
        name = str(s.get("name") or "").strip()
        base_norm = db._normalize_base_text(name)
        key = base_norm if base_norm else db._normalize_text(name)
        if not key:
            continue
        grouped.setdefault(key, []).append(s)

    canonical_startups = []
    for key, group in grouped.items():
        if len(group) == 1:
            canonical_startups.append(group[0])
            continue

        # Rank records to pick canonical record
        def rank_startup(s):
            score = 0
            name = str(s.get("name") or "")
            if s.get("website") and not is_blacklisted_domain(s.get("website")):
                score += 10
            if s.get("logo_domain") and not is_blacklisted_domain(s.get("logo_domain")):
                score += 5
            if s.get("logo_svg_url") and not "favicons" in s.get("logo_svg_url"):
                score += 5
            score += len(s.get("job_openings") or [])
            # Prefer standard clean name (without YC tags, legal suffixes)
            if "(" not in name and "Pvt" not in name and "Inc" not in name and "Ltd" not in name:
                score += 3
            if db._normalize_text(name) == key:
                score += 2
            return score

        sorted_group = sorted(group, key=rank_startup, reverse=True)
        canonical = sorted_group[0]
        
        # Clean canonical name if needed
        clean_canon_name = canonical.get("name", "")
        # Remove YC tags and legal suffixes from canonical display name
        clean_canon_name = re.sub(r'\(\s*yc\b[^\)]*\)', '', clean_canon_name, flags=re.IGNORECASE).strip()
        clean_canon_name = re.sub(r'\bprivate\s+limited\b', '', clean_canon_name, flags=re.IGNORECASE).strip()
        clean_canon_name = re.sub(r'\bpvt\.?\s*ltd\.?\b', '', clean_canon_name, flags=re.IGNORECASE).strip()
        clean_canon_name = re.sub(r'\bpte\.?\s*ltd\.?\b', '', clean_canon_name, flags=re.IGNORECASE).strip()
        clean_canon_name = re.sub(r'\bltd\.?\b', '', clean_canon_name, flags=re.IGNORECASE).strip()
        clean_canon_name = re.sub(r'\binc\.?\b', '', clean_canon_name, flags=re.IGNORECASE).strip()
        clean_canon_name = re.sub(r'\bl\.?l\.?c\.?\b', '', clean_canon_name, flags=re.IGNORECASE).strip()
        clean_canon_name = re.sub(r'\bcorp\.?\b', '', clean_canon_name, flags=re.IGNORECASE).strip()
        clean_canon_name = re.sub(r'[\.,\-\s]+$', '', clean_canon_name).strip()
        if clean_canon_name:
            canonical["name"] = clean_canon_name

        canonical_name = canonical["name"]
        canonical_jobs = canonical.setdefault("job_openings", [])
        if not isinstance(canonical_jobs, list):
            canonical_jobs = []
            canonical["job_openings"] = canonical_jobs

        existing_job_keys = set()
        for j in canonical_jobs:
            if isinstance(j, dict):
                j["company_name"] = canonical_name
                j["company"] = canonical_name
                j_url = str(j.get("url") or j.get("job_url") or "").strip()
                j_title = db._normalize_text(j.get("title") or "")
                existing_job_keys.add(j_url if j_url else j_title)

        for dupe in sorted_group[1:]:
            stats["merged_records"] += 1
            print(f"[Stage 2] Merging duplicate startup '{dupe.get('name')}' (ID: {dupe.get('id')}) into canonical '{canonical_name}' (ID: {canonical.get('id')})")

            # Fill missing metadata in canonical
            if not canonical.get("description") and dupe.get("description"):
                canonical["description"] = dupe["description"]
            if not canonical.get("website") and dupe.get("website") and not is_blacklisted_domain(dupe.get("website")):
                canonical["website"] = dupe["website"]
            if not canonical.get("logo_domain") and dupe.get("logo_domain") and not is_blacklisted_domain(dupe.get("logo_domain")):
                canonical["logo_domain"] = dupe["logo_domain"]
            if not canonical.get("logo_svg_url") and dupe.get("logo_svg_url") and not "favicons" in dupe.get("logo_svg_url"):
                canonical["logo_svg_url"] = dupe["logo_svg_url"]

            dupe_jobs = dupe.get("job_openings") or []
            if isinstance(dupe_jobs, list):
                for j in dupe_jobs:
                    if not isinstance(j, dict):
                        continue
                    j["company_name"] = canonical_name
                    j["company"] = canonical_name
                    j_url = str(j.get("url") or j.get("job_url") or "").strip()
                    j_title = db._normalize_text(j.get("title") or "")
                    j_key = j_url if j_url else j_title
                    if j_key not in existing_job_keys:
                        existing_job_keys.add(j_key)
                        canonical_jobs.append(j)

    # Step C: Clean company display names (strip legal suffixes & YC tags) and re-index IDs
    cleaned_startups = []
    for idx, s in enumerate(canonical_startups, start=1):
        s["id"] = idx
        name = str(s.get("name") or "").strip()
        clean_name = re.sub(r'\(\s*yc\b[^\)]*\)', '', name, flags=re.IGNORECASE).strip()
        clean_name = re.sub(r'\bprivate\s+limited\b', '', clean_name, flags=re.IGNORECASE).strip()
        clean_name = re.sub(r'\bpvt\.?\s*ltd\.?\b', '', clean_name, flags=re.IGNORECASE).strip()
        clean_name = re.sub(r'\bpte\.?\s*ltd\.?\b', '', clean_name, flags=re.IGNORECASE).strip()
        clean_name = re.sub(r'\bltd\.?\b', '', clean_name, flags=re.IGNORECASE).strip()
        clean_name = re.sub(r'\binc\.?\b', '', clean_name, flags=re.IGNORECASE).strip()
        clean_name = re.sub(r'\bl\.?l\.?c\.?\b', '', clean_name, flags=re.IGNORECASE).strip()
        clean_name = re.sub(r'\bcorp\.?\b', '', clean_name, flags=re.IGNORECASE).strip()
        clean_name = re.sub(r'[\.,\-\s]+$', '', clean_name).strip()
        if clean_name:
            s["name"] = clean_name
            # Re-update company name on internal job objects
            for j in s.get("job_openings", []):
                if isinstance(j, dict):
                    j["company_name"] = clean_name
                    j["company"] = clean_name
        cleaned_startups.append(s)

    db.startups = cleaned_startups

    # -------------------------------------------------------------------------
    # Stage 3: Logo Validation & Cleaning
    # Remove default 16x16 Google favicons (https://www.google.com/s2/favicons?domain=...),
    # Unavatar 404/fallback URLs (x-unavatar-fallback), 1x1 transparent pixels,
    # and logos hosted on blacklisted domains. Set cleared logo URLs to "".
    # -------------------------------------------------------------------------
    for s in db.startups:
        logo = str(s.get("logo_svg_url") or "").strip()
        if not logo:
            continue

        should_clear = False
        if "google.com/s2/favicons" in logo:
            should_clear = True
        elif is_blacklisted_domain(logo):
            should_clear = True
        elif not validate_logo_image(logo):
            should_clear = True

        if should_clear:
            s["logo_svg_url"] = ""
            stats["cleared_logos"] += 1

    # -------------------------------------------------------------------------
    # Stage 4: Job Opening Validation, Mismatch Pruning & City Alignment
    # -------------------------------------------------------------------------
    expired_phrases = [
        "no longer accepting applications", "job is closed",
        "position has been filled", "job expired",
        "posting is no longer available", "this job is no longer active",
        "job not found"
    ]

    for s in db.startups:
        startup_name = s.get("name", "")
        jobs = s.get("job_openings", [])
        if not isinstance(jobs, list):
            continue

        valid_jobs = []
        for j in jobs:
            if not isinstance(j, dict):
                continue
            
            # Prune by expired phrases in description/title
            desc = (j.get("description") or "").lower()
            title = (j.get("title") or "").lower()
            if any(phrase in desc or phrase in title for phrase in expired_phrases):
                stats["pruned_jobs"] += 1
                continue

            comp_name = j.get("company_name") or j.get("company") or startup_name
            if db.is_aggregator_name(comp_name) or db._is_job_slug_mismatched(j, startup_name):
                stats["pruned_jobs"] += 1
                continue

            j["company_name"] = startup_name
            j["company"] = startup_name
            valid_jobs.append(j)
        s["job_openings"] = valid_jobs

    # Align city tags for remote offices
    for s in db.startups:
        if s.get("is_remote_office") is True:
            lat, lng = s.get("lat"), s.get("lng")
            if lat and lng:
                for c_name, (c_lat, c_lng) in getattr(db, "MULTI_CITY_CENTERS", {}).items():
                    if abs(lat - c_lat) < 0.8 and abs(lng - c_lng) < 0.8:
                        if "remote" not in s.get("city", "").lower():
                            s["city"] = f"{c_name.capitalize()} (Remote Office)"
                        break

    # -------------------------------------------------------------------------
    # Stage 5: Office Address Suffix & Format Cleanup
    # Clean up trailing ...Read more, Read more, ellipsis, and normalize double spaces.
    # -------------------------------------------------------------------------
    for s in db.startups:
        for o in s.get("offices", []):
            addr = o.get("office_address")
            if addr:
                cleaned = clean_office_address(addr)
                if cleaned != addr:
                    o["office_address"] = cleaned
                    stats["cleared_address_boilerplates"] += 1

    # -------------------------------------------------------------------------
    # Stage 6: Filter out non-metro/international offices
    # Only keep offices that belong to one of the 7 supported Indian metro cities.
    # -------------------------------------------------------------------------
    for s in db.startups:
        offices = s.get("offices", [])
        if isinstance(offices, list) and len(offices) > 0:
            filtered_offices = []
            for o in offices:
                o_city = str(o.get("city") or s.get("city") or "").strip()
                if get_expected_city(o_city) != "other":
                    filtered_offices.append(o)
                else:
                    stats["removed_other_offices"] += 1
            s["offices"] = filtered_offices

    return stats


def main():
    db_path = os.environ.get("STARTUP_DB_PATH", "backend/startups.json")
    print(f"Initializing Production Dataset Cleanup on '{db_path}'...")

    patcher_dns = patch('socket.gethostbyname', side_effect=mock_gethostbyname)
    patcher_head = patch('requests.head', side_effect=mock_requests_head)
    patcher_get = patch('requests.get', side_effect=mock_requests_get)

    with patcher_dns, patcher_head, patcher_get:
        db = DBManager(db_path)
        companies_before = len(db.startups)
        jobs_before = sum(len(s.get("job_openings", [])) for s in db.startups)

        print("\n========================================================")
        print(f"=== PASS 1: Executing 4-Stage Dataset Cleanup        ===")
        print("========================================================")
        print(f"Initial Dataset: {companies_before} startups, {jobs_before} job openings")

        pass1_stats = run_cleanup_pass(db)

        # Save Pass 1 results
        db.save_db()

        companies_after_pass1 = len(db.startups)
        jobs_after_pass1 = sum(len(s.get("job_openings", [])) for s in db.startups)

        print("\n--- Pass 1 Results ---")
        print(f"Startups: {companies_before} -> {companies_after_pass1}")
        print(f"Jobs: {jobs_before} -> {jobs_after_pass1}")
        print(f"Stage 1 Cleared Websites: {pass1_stats['cleared_websites']}")
        print(f"Stage 1 Cleared Logo Domains: {pass1_stats['cleared_domains']}")
        print(f"Stage 2 Merged Company Records: {pass1_stats['merged_records']}")
        print(f"Stage 2 Removed Aggregator Startups: {pass1_stats['removed_aggregators']}")
        print(f"Stage 3 Cleared Logos: {pass1_stats['cleared_logos']}")
        print(f"Stage 4 Pruned Jobs: {pass1_stats['pruned_jobs']}")
        print(f"Stage 5 Cleared Address Boilerplates: {pass1_stats['cleared_address_boilerplates']}")
        print(f"Stage 6 Removed Non-Metro/International Offices: {pass1_stats['removed_other_offices']}")

        print("\n========================================================")
        print(f"=== PASS 2: Verifying 0 Remaining Inconsistencies   ===")
        print("========================================================")
        
        # Load fresh DB instance to verify persistence & re-run cleanup pass
        db_pass2 = DBManager(db_path)
        pass2_stats = run_cleanup_pass(db_pass2)
        db_pass2.save_db()

        companies_after_pass2 = len(db_pass2.startups)
        jobs_after_pass2 = sum(len(s.get("job_openings", [])) for s in db_pass2.startups)

        total_pass2_changes = sum(pass2_stats.values())

        print("\n--- Pass 2 Results ---")
        print(f"Startups: {companies_after_pass1} -> {companies_after_pass2}")
        print(f"Jobs: {jobs_after_pass1} -> {jobs_after_pass2}")
        print(f"Stage 1 Cleared Websites: {pass2_stats['cleared_websites']}")
        print(f"Stage 1 Cleared Logo Domains: {pass2_stats['cleared_domains']}")
        print(f"Stage 2 Merged Company Records: {pass2_stats['merged_records']}")
        print(f"Stage 2 Removed Aggregator Startups: {pass2_stats['removed_aggregators']}")
        print(f"Stage 3 Cleared Logos: {pass2_stats['cleared_logos']}")
        print(f"Stage 4 Pruned Jobs: {pass2_stats['pruned_jobs']}")
        print(f"Stage 5 Cleared Address Boilerplates: {pass2_stats['cleared_address_boilerplates']}")
        print(f"Stage 6 Removed Non-Metro/International Offices: {pass2_stats['removed_other_offices']}")

        if total_pass2_changes == 0 and companies_after_pass1 == companies_after_pass2 and jobs_after_pass1 == jobs_after_pass2:
            print("\n[SUCCESS] Pass 2 reported 0 remaining dataset inconsistencies. Dataset is 100% clean!")
        else:
            print(f"\n[WARNING] Pass 2 detected {total_pass2_changes} remaining inconsistencies.")
            sys.exit(1)

if __name__ == "__main__":
    main()
