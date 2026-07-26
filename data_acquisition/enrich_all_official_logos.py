#!/usr/bin/env python3
"""
Official Website Logo Enricher
Path: data_acquisition/enrich_all_official_logos.py

Scrapes exact official brand logo assets (favicon, apple-touch-icon, og:image, svg)
directly from official company website homepages for all startups in backend/startups.json.
"""

import os
import sys
import json
import urllib.parse
import concurrent.futures
import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_acquisition.utils.validation import is_blacklisted_domain, validate_logo_image

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

def extract_official_logo(startup):
    name = startup.get("name", "Unknown")
    web = str(startup.get("website") or "").strip()
    current_logo = str(startup.get("logo_svg_url") or "").strip()

    if current_logo and current_logo.startswith("http") and not is_blacklisted_domain(current_logo):
        if validate_logo_image(current_logo):
            return name, current_logo, "EXISTS_VALID"

    if not web or not web.startswith(("http://", "https://")) or is_blacklisted_domain(web):
        return name, "", "NO_WEBSITE"

    try:
        res = requests.get(web, headers=DEFAULT_HEADERS, timeout=6, allow_redirects=True)
        if res.status_code != 200:
            return name, "", f"HTTP_{res.status_code}"

        soup = BeautifulSoup(res.text, "html.parser")
        candidates = []

        # 1. Look for SVG or Apple Touch Icon or Favicon links
        for icon in soup.find_all("link", rel=lambda r: r and any(x in str(r).lower() for x in ["apple-touch-icon", "icon", "shortcut icon"])):
            href = icon.get("href")
            if href:
                full_url = urllib.parse.urljoin(res.url, href)
                if not is_blacklisted_domain(full_url):
                    candidates.append(full_url)

        # 2. Look for OpenGraph image (og:image)
        og_img = soup.find("meta", property=lambda p: p and "og:image" in str(p).lower())
        if og_img and og_img.get("content"):
            full_url = urllib.parse.urljoin(res.url, og_img.get("content"))
            if not is_blacklisted_domain(full_url):
                candidates.append(full_url)

        # 3. Look for header/brand img tags
        for img in soup.find_all("img", src=True):
            src = img.get("src", "")
            alt = (img.get("alt") or "").lower()
            cls = " ".join(img.get("class") or []).lower()
            if "logo" in src.lower() or "logo" in alt or "logo" in cls or "brand" in cls:
                full_url = urllib.parse.urljoin(res.url, src)
                if not is_blacklisted_domain(full_url):
                    candidates.append(full_url)

        for cand in candidates:
            if validate_logo_image(cand):
                return name, cand, "ENRICHED"

    except Exception as e:
        return name, "", f"ERROR: {type(e).__name__}"

    return name, "", "NOT_FOUND"


def main():
    db_path = os.path.join(PROJECT_ROOT, "backend", "startups.json")
    with open(db_path, "r", encoding="utf-8") as f:
        startups = json.load(f)

    print(f"Enriching official logos for {len(startups)} startups from official websites...")

    enriched_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        results = list(executor.map(extract_official_logo, startups))

    res_map = {r[0]: (r[1], r[2]) for r in results}

    for s in startups:
        name = s.get("name")
        if name in res_map:
            logo_url, status = res_map[name]
            if logo_url and logo_url != s.get("logo_svg_url"):
                s["logo_svg_url"] = logo_url
                enriched_count += 1

    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(startups, f, indent=2)

    print(f"\n[SUCCESS] Enriched official logos for {enriched_count} startups directly from official homepages!")
    print(f"Updated database saved to: {db_path}")


if __name__ == "__main__":
    main()
