#!/usr/bin/env python3
"""
Database Startup Deduplication & Merging Script
Path: data_acquisition/deduplicate_startups.py

Merges duplicate records of the same company in the same metro city:
- Keeps canonical record with the lowest ID (e.g., Google ID 14).
- Merges all job_openings from duplicates (e.g., Google ID 24) into the canonical record.
- Inherits any richer metadata (logo_svg_url, website, office_address) if the canonical record has an empty field.
- Removes duplicate records and synchronizes backend/startups.json -> public/static/data/startups.json.
"""

import json
import os
import re
import shutil
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.db_manager import DBManager

def get_metro_city(city_str):
    c = str(city_str or "").lower()
    if any(k in c for k in ["mumbai", "thane", "navi mumbai", "kalyan", "powai", "andheri", "bkc"]): return "Mumbai"
    if "kolkata" in c: return "Kolkata"
    if "chennai" in c: return "Chennai"
    if any(k in c for k in ["hyderabad", "secunderabad", "gachibowli", "hitech", "madhapur"]): return "Hyderabad"
    if "pune" in c: return "Pune"
    if any(k in c for k in ["delhi", "noida", "gurugram", "gurgaon", "ncr", "faridabad", "ghaziabad", "greater noida"]): return "Delhi NCR"
    return "Bengaluru"

def normalize_company_name(name):
    if not name or not isinstance(name, str):
        return ""
    n = name.lower()
    # Remove country/legal suffixes
    n = re.sub(r'\b(in india|india|pvt|private|limited|ltd|inc|corp|llp|technologies|solutions|services)\b', '', n)
    # Remove punctuation
    n = re.sub(r'[^a-z0-9]', '', n)
    return n.strip()

def merge_duplicate_startups():
    db_path = os.path.join(PROJECT_ROOT, "backend", "startups.json")
    public_db_path = os.path.join(PROJECT_ROOT, "public", "static", "data", "startups.json")

    print(f"=== DEDUPLICATING STARTUPS IN {db_path} ===")
    with open(db_path, "r") as f:
        startups = json.load(f)

    # Sort by ID ascending so lowest ID is processed first as canonical
    startups.sort(key=lambda x: int(x.get("id", 99999)))

    canonical_map = {}  # key -> startup dict
    deduped_list = []
    merged_count = 0

    for s in startups:
        raw_name = str(s.get("name") or "")
        norm_name = normalize_company_name(raw_name)
        metro = get_metro_city(s.get("city"))
        key = (norm_name, metro)

        if not norm_name:
            deduped_list.append(s)
            continue

        if key in canonical_map:
            canonical = canonical_map[key]
            print(f"[Merge] ID {s['id']:3d} ('{raw_name}') -> canonical ID {canonical['id']:3d} ('{canonical['name']}') in {metro}")

            # 1. Merge job openings
            canonical_jobs = canonical.setdefault("job_openings", [])
            existing_urls = {j.get("url") or j.get("job_url") for j in canonical_jobs if isinstance(j, dict)}

            for job in s.get("job_openings", []):
                if isinstance(job, dict):
                    j_url = job.get("url") or job.get("job_url")
                    if j_url and j_url not in existing_urls:
                        canonical_jobs.append(job)
                        existing_urls.add(j_url)

            # 2. Inherit richer metadata if canonical field is empty/generic
            for field in ["website", "logo_svg_url", "logo_domain", "description", "office_address"]:
                can_val = str(canonical.get(field) or "").strip()
                dup_val = str(s.get(field) or "").strip()
                if not can_val and dup_val and dup_val.lower() != "n/a":
                    canonical[field] = dup_val

            merged_count += 1
        else:
            canonical_map[key] = s
            deduped_list.append(s)

    with open(db_path, "w") as f:
        json.dump(deduped_list, f, indent=2)

    shutil.copy2(db_path, public_db_path)
    print(f"✅ DEDUPLICATION COMPLETED!")
    print(f"   Original startups count : {len(startups)}")
    print(f"   Merged duplicate count  : {merged_count}")
    print(f"   Final unique count      : {len(deduped_list)}")
    print(f"   Synchronized {db_path} -> {public_db_path}")

    return merged_count

if __name__ == "__main__":
    merge_duplicate_startups()
