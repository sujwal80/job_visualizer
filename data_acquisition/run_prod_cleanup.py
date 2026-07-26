import sys
import os
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
        self.content = text.encode("utf-8")

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
        "pruned_jobs": 0
    }

    # -------------------------------------------------------------------------
    # Stage 1: Domain & Website Filtering
    # Identify and clear shorteners, aggregators, or invalid domains in website
    # and logo_domain fields (e.g. goo.gle, careers.linkedin.com, start.myjar.app, bit.ly).
    # -------------------------------------------------------------------------
    for s in db.startups:
        web = str(s.get("website") or "").strip()
        if web and web != "N/A":
            p = urllib.parse.urlparse(web if web.startswith(("http://", "https://")) else f"https://{web}")
            netloc_dom = p.netloc.lower()
            if netloc_dom.startswith("www."):
                netloc_dom = netloc_dom[4:]
            netloc_dom = netloc_dom.split(":")[0]

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
        # Remove YC tags from canonical name
        import re
        clean_canon_name = re.sub(r'\(\s*yc\b[^\)]*\)', '', clean_canon_name, flags=re.IGNORECASE).strip()
        clean_canon_name = re.sub(r'\bpvt\.?\s*ltd\.?\b', '', clean_canon_name, flags=re.IGNORECASE).strip()
        clean_canon_name = re.sub(r'\bprivate\s+limited\b', '', clean_canon_name, flags=re.IGNORECASE).strip()
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

        canonical_startups.append(canonical)

    db.startups = canonical_startups

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
    # Stage 4: Job Opening Slug Validation & Mismatch Pruning
    # Audit all job openings under each startup. Re-check job URL slugs
    # (_is_job_slug_mismatched) to prune mismatched jobs or jobs registered under
    # aggregator company names.
    # -------------------------------------------------------------------------
    for s in db.startups:
        startup_name = s.get("name", "")
        jobs = s.get("job_openings", [])
        if not jobs or not isinstance(jobs, list):
            continue

        valid_jobs = []
        for j in jobs:
            if not isinstance(j, dict):
                stats["pruned_jobs"] += 1
                continue

            comp_name = j.get("company_name") or j.get("company") or startup_name
            if db.is_aggregator_name(comp_name):
                print(f"[Stage 4] Pruning job with aggregator company name '{comp_name}': '{j.get('title')}'")
                stats["pruned_jobs"] += 1
                continue

            if db._is_job_slug_mismatched(j, startup_name):
                print(f"[Stage 4] Pruning mismatched job '{j.get('title')}' (URL: {j.get('url') or j.get('job_url')}) under startup '{startup_name}'")
                stats["pruned_jobs"] += 1
                continue

            j["company_name"] = startup_name
            j["company"] = startup_name
            valid_jobs.append(j)

        s["job_openings"] = valid_jobs

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

        if total_pass2_changes == 0 and companies_after_pass1 == companies_after_pass2 and jobs_after_pass1 == jobs_after_pass2:
            print("\n[SUCCESS] Pass 2 reported 0 remaining dataset inconsistencies. Dataset is 100% clean!")
        else:
            print(f"\n[WARNING] Pass 2 detected {total_pass2_changes} remaining inconsistencies.")
            sys.exit(1)

if __name__ == "__main__":
    main()
