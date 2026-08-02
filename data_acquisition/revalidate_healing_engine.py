#!/usr/bin/env python3
"""
Continuous Online Re-Validation & Safe Healing Engine
Path: data_acquisition/revalidate_healing_engine.py

Core engine responsible for:
- Foreign regional TLD healing (.it, .de, .fr, .es, .au, .br -> .com or .in)
- City-scoped deduplication ((normalize_company_name(name), get_metro_city(city)))
- Street address zero-regression guardrails (never overwrite verified street addresses with generic city labels)
- Bounding box coordinate verification across all 7 Indian metro cities (Bengaluru, Hyderabad, Delhi NCR, Chennai, Kolkata, Pune, Mumbai)
"""

import argparse
import json
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.db_manager import DBManager
from data_acquisition.deduplicate_startups import normalize_company_name, get_metro_city

METRO_CITIES = [
    "Bengaluru",
    "Hyderabad",
    "Delhi NCR",
    "Chennai",
    "Kolkata",
    "Pune",
    "Mumbai"
]

CITY_BOUNDS = {
    "Mumbai": {"lat": (18.8, 19.4), "lng": (72.7, 73.1), "default": (19.0760, 72.8777)},
    "Bengaluru": {"lat": (12.8, 13.2), "lng": (77.4, 77.8), "default": (12.9716, 77.5946)},
    "Hyderabad": {"lat": (17.2, 17.6), "lng": (78.3, 78.7), "default": (17.3850, 78.4867)},
    "Chennai": {"lat": (12.8, 13.2), "lng": (80.1, 80.4), "default": (13.0827, 80.2707)},
    "Kolkata": {"lat": (22.4, 22.7), "lng": (88.2, 88.5), "default": (22.5726, 88.3639)},
    "Pune": {"lat": (18.4, 18.7), "lng": (73.7, 74.0), "default": (18.5204, 73.8567)},
    "Delhi": {"lat": (28.4, 28.9), "lng": (77.0, 77.4), "default": (28.6139, 77.2090)},
    "Delhi NCR": {"lat": (28.4, 28.9), "lng": (77.0, 77.4), "default": (28.6139, 77.2090)}
}


def normalize_text(text):
    if not text or not isinstance(text, str):
        return ""
    return re.sub(r'[^a-z0-9]', '', text.lower()).strip()


class RevalidationHealingEngine:
    def __init__(self, db_path="backend/startups.json"):
        self.db_path = os.path.abspath(db_path)
        self.db_manager = DBManager(self.db_path)

    def _heal_tld_string(self, text):
        if not text or not isinstance(text, str):
            return text, False
        scheme_match = re.match(r'^(https?://)(.*)', text, re.IGNORECASE)
        if scheme_match:
            scheme = scheme_match.group(1)
            remainder = scheme_match.group(2)
        else:
            scheme = ""
            remainder = text
        sep_match = re.search(r'[/?#]', remainder)
        if sep_match:
            idx = sep_match.start()
            auth = remainder[:idx]
            rest = remainder[idx:]
        else:
            auth = remainder
            rest = ""
        authority_part = scheme + auth
        pattern = r'\.(?:com\.)?(it|de|fr|es|au|br)(?=(?::\d+)?$)'
        if re.search(pattern, authority_part, re.IGNORECASE):
            healed_auth = re.sub(pattern, '.com', authority_part, flags=re.IGNORECASE)
            healed = healed_auth + rest
            return healed, True
        return text, False

    def heal_foreign_tlds(self, records) -> int:
        """
        Heal 100% of foreign regional TLDs (.it, .de, .fr, .es, .au, .br) to canonical .com
        without modifying valid existing .com/.in/.tech domains.
        Returns the number of records healed.
        """
        healed_count = 0
        for s in records:
            if not isinstance(s, dict):
                continue
            healed_record = False
            web = s.get("website")
            if web:
                new_web, changed = self._heal_tld_string(web)
                if changed:
                    s["website"] = new_web
                    healed_record = True

            dom = s.get("logo_domain")
            if dom:
                new_dom, changed = self._heal_tld_string(dom)
                if changed:
                    s["logo_domain"] = new_dom
                    healed_record = True

            logo_svg = s.get("logo_svg_url")
            if logo_svg:
                new_logo_svg, changed = self._heal_tld_string(logo_svg)
                if changed:
                    s["logo_svg_url"] = new_logo_svg
                    healed_record = True

            job_openings = s.get("job_openings")
            if isinstance(job_openings, list):
                for job in job_openings:
                    if isinstance(job, dict):
                        for url_field in ["url", "job_url"]:
                            job_url = job.get(url_field)
                            if job_url:
                                new_job_url, changed = self._heal_tld_string(job_url)
                                if changed:
                                    job[url_field] = new_job_url
                                    healed_record = True

            if healed_record:
                healed_count += 1

        return healed_count

    def deduplicate_city_records(self, records) -> int:
        """
        Group records by (normalize_company_name(name), get_metro_city(city)).
        For duplicates in the same metro city, keep the canonical lowest-ID record,
        merge unique job_openings, inherit richer metadata, and remove duplicate entries.
        Zero-Regression Guardrail: NEVER merge records of the same company across different metro cities.
        Returns the number of duplicate records merged and removed.
        """
        records.sort(key=lambda x: int(x.get("id", 99999)) if isinstance(x, dict) else 99999)

        canonical_map = {}
        deduped_list = []
        merged_count = 0

        for s in records:
            if not isinstance(s, dict):
                continue
            raw_name = str(s.get("name") or "")
            norm_name = normalize_company_name(raw_name)
            metro = get_metro_city(s.get("city"))
            key = (norm_name, metro)

            if not norm_name:
                deduped_list.append(s)
                continue

            if key in canonical_map:
                canonical = canonical_map[key]
                # 1. Merge job openings
                canonical_jobs = canonical.setdefault("job_openings", [])
                existing_job_keys = {
                    (normalize_text(j.get("title")), j.get("url") or j.get("job_url") or "")
                    for j in canonical_jobs
                    if isinstance(j, dict)
                }
                for job in s.get("job_openings", []):
                    if isinstance(job, dict):
                        job_key = (normalize_text(job.get("title")), job.get("url") or job.get("job_url") or "")
                        if job_key not in existing_job_keys:
                            canonical_jobs.append(job)
                            existing_job_keys.add(job_key)

                # 2. Inherit richer metadata if canonical field is empty or generic
                for field in [
                    "website",
                    "logo_svg_url",
                    "logo_domain",
                    "description",
                    "office_address",
                    "verified_email",
                    "bangalore_address",
                    "industry",
                    "funding_stage",
                ]:
                    can_val = str(canonical.get(field) or "").strip()
                    dup_val = str(s.get(field) or "").strip()
                    if not can_val and dup_val and dup_val.lower() != "n/a":
                        canonical[field] = dup_val
                    elif field in ("office_address", "bangalore_address") and dup_val and dup_val.lower() != "n/a":
                        can_verified = self._is_verified_street_address(can_val) or canonical.get("_address_verified_guardrail", False)
                        dup_verified = self._is_verified_street_address(dup_val) or s.get("_address_verified_guardrail", False)
                        if dup_verified and not can_verified:
                            canonical[field] = dup_val
                            if s.get("_address_verified_guardrail", False):
                                canonical["_address_verified_guardrail"] = True

                # 3. Inherit headcount if higher
                if s.get("head_count", 0) > canonical.get("head_count", 0):
                    canonical["head_count"] = s["head_count"]

                merged_count += 1
            else:
                canonical_map[key] = s
                deduped_list.append(s)

        records[:] = deduped_list
        return merged_count

    def _is_verified_street_address(self, address) -> bool:
        if not address or not isinstance(address, str):
            return False
        addr_clean = address.strip()
        if not addr_clean or addr_clean.lower() == "n/a":
            return False

        addr_no_pin = re.sub(r'\b\d{6}\b', '', addr_clean).strip()
        addr_no_pin = re.sub(r'\s+,', ',', addr_no_pin).strip()
        addr_no_pin = re.sub(r',\s*$', '', addr_no_pin).strip()

        generic_patterns = [
            r'^[A-Za-z\s,-]+,\s*(India|Karnataka|Maharashtra|Telangana|Tamil Nadu|West Bengal|Delhi|NCR|Haryana|UP|Uttar Pradesh|Bengaluru|Mumbai|Hyderabad|Chennai|Kolkata|Pune)$',
            r'^[A-Za-z\s]+$'
        ]
        for pat in generic_patterns:
            if re.match(pat, addr_no_pin, re.IGNORECASE):
                return False

        keywords = [
            "layout", "nagar", "road", "rd", "street", "st", "floor", "building", "tower", "block",
            "plot", "phase", "sector", "cross", "main", "area", "park", "enclave", "complex",
            "hsr", "koramangala", "indiranagar", "whitefield", "ecospace", "marathahalli",
            "jayanagar", "jp nagar", "powai", "andheri", "bkc", "bandra", "gachibowli", "hitech",
            "madhapur", "jubilee", "banjara", "salt lake", "new town", "connaught", "gurugram",
            "noida", "adyar", "guindy", "velachery", "baner", "hinjewadi", "kalyani", "viman"
        ]
        lower_addr = addr_clean.lower()
        if any(kw in lower_addr for kw in keywords) or any(char.isdigit() for char in addr_no_pin):
            return True

        return False

    def verify_address_guardrails(self, records) -> int:
        """
        Ensure verified OpenStreetMap street addresses are NEVER overwritten by a generic
        city name or default label (f"{city}, India" or "City, State").
        Returns the number of verified street addresses preserved.
        """
        preserved_count = 0
        for s in records:
            if not isinstance(s, dict):
                continue
            addr = s.get("office_address") or ""
            if self._is_verified_street_address(addr):
                preserved_count += 1
                # Guardrail: protect verified address from being overwritten by generic label
                s["_address_verified_guardrail"] = True

        return preserved_count

    def verify_and_heal_coordinates(self, records) -> int:
        """
        Ensure all coordinate pairs (lat, lng) lie within CITY_BOUNDS[metro].
        Returns the number of out-of-bounds coordinates fixed.
        """
        fixed_count = 0
        for s in records:
            if not isinstance(s, dict):
                continue
            metro = get_metro_city(s.get("city"))
            bounds = CITY_BOUNDS.get(metro, CITY_BOUNDS["Bengaluru"])

            lat_raw = s.get("lat")
            lng_raw = s.get("lng")
            lat, lng = None, None
            try:
                if lat_raw is not None and lng_raw is not None:
                    lat = float(lat_raw)
                    lng = float(lng_raw)
            except (ValueError, TypeError):
                lat, lng = None, None

            in_bounds = (
                lat is not None and lng is not None and
                bounds["lat"][0] <= lat <= bounds["lat"][1] and
                bounds["lng"][0] <= lng <= bounds["lng"][1]
            )

            if in_bounds:
                if isinstance(lat_raw, str):
                    s["lat"] = lat
                if isinstance(lng_raw, str):
                    s["lng"] = lng
            else:
                s["lat"] = bounds["default"][0]
                s["lng"] = bounds["default"][1]
                fixed_count += 1

        return fixed_count

    def revalidate_and_heal_all(self, dry_run=False) -> dict:
        """
        Audit and heal all records across the 7 Indian metro cities.
        Returns metrics dict containing:
          - foreign_tlds_healed
          - duplicates_merged
          - addresses_preserved
          - out_of_bounds_fixed
          - total_records
        """
        with DBManager.file_lock(self.db_path):
            with open(self.db_path, "r", encoding="utf-8") as f:
                records = json.load(f)

            foreign_tlds_healed = self.heal_foreign_tlds(records)
            duplicates_merged = self.deduplicate_city_records(records)
            addresses_preserved = self.verify_address_guardrails(records)
            out_of_bounds_fixed = self.verify_and_heal_coordinates(records)

            if not dry_run:
                abs_db_path = os.path.abspath(self.db_path)
                os.makedirs(os.path.dirname(abs_db_path), exist_ok=True)
                tmp_path = abs_db_path + ".tmp_heal"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(records, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, abs_db_path)

            return {
                "foreign_tlds_healed": foreign_tlds_healed,
                "duplicates_merged": duplicates_merged,
                "addresses_preserved": addresses_preserved,
                "out_of_bounds_fixed": out_of_bounds_fixed,
                "total_records": len(records)
            }


def main():
    parser = argparse.ArgumentParser(description="Continuous Online Re-Validation & Safe Healing Engine")
    parser.add_argument("--db", default="backend/startups.json", help="Path to startups database JSON")
    parser.add_argument("--dry-run", action="store_true", help="Perform audit without saving changes")
    args = parser.parse_args()

    engine = RevalidationHealingEngine(db_path=args.db)
    metrics = engine.revalidate_and_heal_all(dry_run=args.dry_run)
    print(f"=== RE-VALIDATION & HEALING COMPLETE (dry_run={args.dry_run}) ===")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
