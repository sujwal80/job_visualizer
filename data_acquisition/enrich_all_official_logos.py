#!/usr/bin/env python3
"""
High-Quality Logo & Brand Asset Enricher (Chrome CDP + HTTP Fallback)
Path: data_acquisition/enrich_all_official_logos.py

Enriches startups in backend/startups.json with the highest quality official logos available
by crawling LinkedIn company profiles and official website homepages using Google Chrome with
an authenticated login profile (via Chrome DevTools Protocol over WebSockets), avoiding
Cloudflare blocks, bot detection, and login walls.

Key Features & Rules:
1. Uses Google Chrome with a user profile directory (e.g. ~/starup_visualizer/chrome_profile_healer)
   to ensure authenticated session state (LinkedIn login, Cloudflare cookies) is preserved.
2. Evaluates live rendered DOM to extract exact high-resolution brand logos:
   - Tier 1 (100 pts): Official Homepage Vector SVG logo (<link rel="icon" ... .svg>, header/nav SVG).
   - Tier 2 ( 95 pts): LinkedIn Company Profile Avatar (licdn.com/dms/image/.../company-logo).
   - Tier 3 ( 90 pts): Homepage Apple Touch Icon or High-Res Web Manifest Icon (180x180+).
   - Tier 4 ( 80 pts): Homepage Header/Navbar PNG brand logo (verified dimensions & aspect ratio).
   - Tier 5 ( 65 pts): Verified Unavatar API (https://unavatar.io/{domain}).
   - Tier 6 ( 55 pts): Google Favicon API at sz=256.
3. Strictly crawls LOGOS ONLY: Rejects marketing banners, hero backgrounds, promotional slides,
   team photos, 1x1 tracking pixels, low-res 16x16 favicons, and blacklisted domains.
4. Automatically synchronizes backend/startups.json and public/static/data/startups.json.
"""

import os
import sys
import time
import json
import asyncio
import subprocess
import urllib.parse
import re
import random
import shutil
import concurrent.futures
import requests
from bs4 import BeautifulSoup

try:
    import websockets
except ImportError:
    websockets = None

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from data_acquisition.utils.validation import (
        is_blacklisted_domain,
        validate_logo_image,
        safe_http_request,
    )
except ImportError:
    from utils.validation import (
        is_blacklisted_domain,
        validate_logo_image,
        safe_http_request,
    )

try:
    from data_acquisition.enrich_issue_logos import MANUAL_LOGO_OVERRIDES
except ImportError:
    MANUAL_LOGO_OVERRIDES = {}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like"
        " Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    ),
}


def get_logo_candidate_score(url, source_type, width=0, height=0):
    """Calculates a Quality Score (0-100) for a candidate logo URL based on source type and resolution."""
    if (
        not url
        or not isinstance(url, str)
        or not url.startswith(("http://", "https://"))
    ):
        return 0

    url_lower = url.lower()
    # Reject junk advertising, banners, cover images, and tracking pixels
    junk_keywords = [
        ".gif",
        "/banner/",
        "banner",
        "hero",
        "slide",
        "1200x",
        "ogimage",
        "footer",
        "about",
        "team",
        "cover",
        "background",
        "promo",
        "discount",
    ]
    if any(kw in url_lower for kw in junk_keywords):
        return 0

    # Dimension checks if available from DOM
    if width > 0 and height > 0:
        if width == 1 or height == 1 or width < 20 or height < 20:
            return 0  # Reject tracking pixels and tiny icons
        if (
            width / height > 8.0 or height / width > 4.0
        ):  # Reject wide banners or tall strips
            return 0

    if source_type == "svg_icon" or (
        source_type in ("svg_logo", "brand_img", "icon") and url_lower.endswith(".svg")
    ):
        return 100
    if source_type == "linkedin_logo" or "company-logo" in url_lower:
        return 95
    if (
        source_type == "apple_touch_icon"
        or "apple-touch-icon" in url_lower
        or source_type == "highres_icon"
    ):
        return 90
    if source_type == "highres_brand_img":
        return 80
    if source_type == "brand_img":
        return 75
    if source_type == "unavatar" or "unavatar.io" in url_lower:
        return 65
    if source_type == "google_favicon" or "google.com/s2/favicons" in url_lower:
        return 55

    return 50


def check_unavatar_api(domain):
    """Checks Unavatar API for high-resolution company logos."""
    if not domain or is_blacklisted_domain(domain):
        return None
    try:
        url = f"https://unavatar.io/{domain}?fallback=false"
        resp = safe_http_request("GET", url, timeout=5, headers=DEFAULT_HEADERS)
        if resp.status_code == 200 and validate_logo_image(url):
            return f"https://unavatar.io/{domain}"
    except Exception:
        pass
    return None


def check_google_favicon_api(domain):
    """Checks Google Favicon API at 256x256 resolution."""
    if not domain or is_blacklisted_domain(domain):
        return None
    try:
        url = f"https://www.google.com/s2/favicons?domain={domain}&sz=256"
        resp = safe_http_request("GET", url, timeout=5, headers=DEFAULT_HEADERS)
        if resp.status_code == 200 and validate_logo_image(url):
            return url
    except Exception:
        pass
    return None


def extract_domain(website):
    """Extracts cleanly cleaned domain from website URL."""
    if not website:
        return ""
    try:
        parsed = urllib.parse.urlparse(str(website).strip())
        domain = parsed.netloc.lower() or parsed.path.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        domain = domain.split("/")[0].split(":")[0]
        if is_blacklisted_domain(domain):
            return ""
        return domain
    except Exception:
        return ""


def extract_linkedin_slug(startup):
    """Extracts company_slug for LinkedIn from job_openings, URLs, or normalized company name."""
    if not isinstance(startup, dict):
        return None
    # 1. Explicit company_slug in job openings
    for job in startup.get("job_openings", []):
        slug = job.get("company_slug")
        if slug and isinstance(slug, str) and len(slug) > 1:
            return slug.strip()
    # 2. Extract from job URLs matching -at-<company_slug>-<job_id>
    for job in startup.get("job_openings", []):
        job_link = str(job.get("url") or job.get("job_url") or "")
        if "-at-" in job_link:
            m = re.search(r"-at-([a-zA-Z0-9\-]+)-\d+", job_link)
            if m:
                s = m.group(1).strip("-")
                if s and not is_blacklisted_domain(s) and len(s) > 1:
                    return s
    # 3. Check if a linkedin URL is stored anywhere on startup
    for k in ("linkedin_url", "linkedin", "linkedin_slug"):
        val = str(startup.get(k) or "").strip()
        if val:
            if "/" in val:
                parts = [
                    p
                    for p in urllib.parse.urlparse(val).path.strip("/").split("/")
                    if p
                ]
                if len(parts) >= 2 and parts[0] == "company":
                    return parts[1]
                elif len(parts) == 1:
                    return parts[0]
            else:
                return val
    # 4. Normalized name fallback
    name = str(startup.get("name") or "").strip()
    if name and name != "N/A":
        clean_name = re.sub(r'[^a-zA-Z0-9]+', '-', name).strip('-').lower()
        if clean_name and not is_blacklisted_domain(clean_name) and len(clean_name) > 2:
            return clean_name
    return None


async def get_ws_browser_url(port=9334):
    """Polls Chrome debugger port until ready."""
    for _ in range(15):
        try:
            res = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=2)
            if res.status_code == 200:
                return res.json()["webSocketDebuggerUrl"]
        except Exception:
            pass
        await asyncio.sleep(1)
    return None


async def extract_candidates_via_chrome(ws_page, url, page_type="website"):
    """Injects JavaScript into live Chrome tab to harvest high quality logo icon candidates from DOM."""
    if not ws_page or not url or not url.startswith(("http://", "https://")):
        return []

    try:
        nav_cmd = {
            "id": int(time.time() * 1000) % 100000 + 1,
            "method": "Runtime.evaluate",
            "params": {"expression": f"window.location.href = '{url}'"},
        }
        await ws_page.send(json.dumps(nav_cmd))
        await ws_page.recv()
        await asyncio.sleep(3.5)  # Wait for JavaScript / React / Next.js to render DOM

        if page_type == "linkedin":
            js_expr = """
            (() => {
                const candidates = [];
                const logoSelectors = [
                    '.org-top-card-primary-content__logo-container img',
                    '.org-top-card-summary__logo-container img',
                    '.artdeco-entity-image--company',
                    'img.org-top-card-primary-content__logo',
                    '.org-top-card-summary-info-list img',
                    'img[src*="licdn.com/dms/image"][src*="company-logo"]'
                ];
                logoSelectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(img => {
                        const src = img.src || img.getAttribute('data-delayed-url') || img.getAttribute('data-ghost-url');
                        if (src && src.startsWith('http') && !src.includes('/ghost/')) {
                            if (!img.className.includes('cover') && !img.className.includes('banner')) {
                                candidates.push({url: src, type: 'linkedin_logo', width: img.naturalWidth || 400, height: img.naturalHeight || 400});
                            }
                        }
                    });
                });
                document.querySelectorAll('img').forEach(img => {
                    const src = img.src || img.getAttribute('data-delayed-url') || '';
                    if (src.includes('licdn.com') && src.includes('company-logo')) {
                        candidates.push({url: src, type: 'linkedin_logo', width: 200, height: 200});
                    }
                });
                return JSON.stringify(candidates);
            })()
            """
        else:
            js_expr = """
            (() => {
                const candidates = [];
                document.querySelectorAll('link[rel*="icon" i], link[rel*="apple-touch-icon" i]').forEach(l => {
                    if (!l.href || !l.href.startsWith('http')) return;
                    const rel = (l.getAttribute('rel') || '').toLowerCase();
                    const sizes = (l.getAttribute('sizes') || '').toLowerCase();
                    let type = 'icon';
                    if (l.href.toLowerCase().endsWith('.svg') || l.type === 'image/svg+xml') type = 'svg_icon';
                    else if (rel.includes('apple-touch-icon')) type = 'apple_touch_icon';
                    else if (sizes.includes('192') || sizes.includes('256') || sizes.includes('512') || sizes.includes('128')) type = 'highres_icon';
                    candidates.push({url: l.href, type: type, width: 192, height: 192});
                });
                document.querySelectorAll('header img, nav img, .navbar img, .header img, a[class*="brand" i] img, a[class*="logo" i] img, img[class*="logo" i], img[id*="logo" i], img[alt*="logo" i], img[src*="logo" i]').forEach(img => {
                    const src = img.src || img.getAttribute('data-src') || img.getAttribute('data-delayed-url');
                    if (!src || src.startsWith('data:') || !src.startsWith('http')) return;
                    const srcLower = src.toLowerCase();
                    const junk = ['.gif', 'banner', 'hero', 'slide', 'ogimage', 'footer', 'about', 'team', '1200x', 'cover'];
                    if (junk.some(j => srcLower.includes(j))) return;
                    const w = img.naturalWidth || img.width || 0;
                    const h = img.naturalHeight || img.height || 0;
                    if (w > 0 && h > 0) {
                        if (w === 1 || h === 1 || w < 20 || h < 20) return;
                        if (w / h > 8.0 || h / w > 4.0) return;
                    }
                    let type = 'brand_img';
                    if (srcLower.endsWith('.svg')) type = 'svg_logo';
                    else if (w >= 100 && h >= 30) type = 'highres_brand_img';
                    candidates.push({url: src, type: type, width: w, height: h});
                });
                return JSON.stringify(candidates);
            })()
            """

        cmd = {
            "id": int(time.time() * 1000) % 100000 + 2,
            "method": "Runtime.evaluate",
            "params": {"expression": js_expr},
        }
        await ws_page.send(json.dumps(cmd))
        resp = json.loads(await ws_page.recv())
        val = resp.get("result", {}).get("result", {}).get("value", "[]")
        return json.loads(val)
    except Exception as e:
        print(f"[Chrome CDP] Error extracting from {url}: {e}")
        return []


def extract_candidates_via_http(url):
    """Fallback HTTP requests extractor for homepages when Chrome is unavailable."""
    if not url or not url.startswith(("http://", "https://")):
        return []
    candidates = []
    try:
        res = requests.get(
            url, headers=DEFAULT_HEADERS, timeout=6, allow_redirects=True
        )
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for icon in soup.find_all(
                "link",
                rel=lambda r: (
                    r
                    and any(
                        x in str(r).lower()
                        for x in ["apple-touch-icon", "icon", "shortcut icon"]
                    )
                ),
            ):
                href = icon.get("href")
                if href:
                    full_url = urllib.parse.urljoin(res.url, href)
                    rel_str = str(icon.get("rel") or "").lower()
                    c_type = "svg_icon" if full_url.endswith(".svg") else "icon"
                    if "apple-touch-icon" in rel_str:
                        c_type = "apple_touch_icon"
                    if not is_blacklisted_domain(full_url):
                        candidates.append(
                            {
                                "url": full_url,
                                "type": c_type,
                                "width": 180,
                                "height": 180,
                            }
                        )

            for img in soup.find_all("img", src=True):
                src = img.get("src", "")
                if any(
                    bad in src.lower()
                    for bad in [
                        ".gif",
                        "/banner/",
                        "banner",
                        "hero",
                        "1200x",
                        "ogimage",
                        "footer_logo",
                        "about",
                        "team",
                    ]
                ):
                    continue
                alt = (img.get("alt") or "").lower()
                cls = " ".join(img.get("class") or []).lower()
                if (
                    "logo" in src.lower()
                    or "logo" in alt
                    or "logo" in cls
                    or "brand" in cls
                ):
                    full_url = urllib.parse.urljoin(res.url, src)
                    if not is_blacklisted_domain(full_url):
                        c_type = (
                            "svg_logo"
                            if full_url.endswith(".svg")
                            else "brand_img"
                        )
                        candidates.append(
                            {"url": full_url, "type": c_type, "width": 0, "height": 0}
                        )
    except Exception:
        pass
    return candidates


def extract_linkedin_candidates_via_http(slug):
    """Fetches public LinkedIn company profile and extracts company avatar logo."""
    if not slug or is_blacklisted_domain(slug):
        return []
    candidates = []
    try:
        url = f"https://www.linkedin.com/company/{slug}"
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=6, allow_redirects=True)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-delayed-url") or ""
                if "licdn.com" in src and "company-logo" in src:
                    if not is_blacklisted_domain(src):
                        candidates.append({"url": src, "type": "linkedin_logo", "width": 200, "height": 200})
                        break
    except Exception:
        pass
    return candidates


def extract_official_logo(startup):
    """Synchronous fallback/interface compatibility method for single-startup extraction without Chrome."""
    name = startup.get("name", "Unknown")
    web = str(startup.get("website") or "").strip()
    current_logo = str(startup.get("logo_svg_url") or "").strip()

    if name in MANUAL_LOGO_OVERRIDES:
        return name, MANUAL_LOGO_OVERRIDES[name], "MANUAL_OVERRIDE"

    domain = extract_domain(web) or str(startup.get("logo_domain") or "").strip()

    # If already a vector SVG and valid, keep it
    if current_logo and current_logo.lower().endswith(".svg"):
        if validate_logo_image(current_logo):
            return name, current_logo, "EXISTS_VALID_SVG"

    candidates = []
    # 1. Check LinkedIn profile
    ln_slug = extract_linkedin_slug(startup)
    if ln_slug:
        candidates.extend(extract_linkedin_candidates_via_http(ln_slug))

    # 2. Check website homepage
    if web and not is_blacklisted_domain(web):
        candidates.extend(extract_candidates_via_http(web))

    if domain and not is_blacklisted_domain(domain):
        unav = check_unavatar_api(domain)
        if unav:
            candidates.append({"url": unav, "type": "unavatar", "width": 0, "height": 0})
        gfav = check_google_favicon_api(domain)
        if gfav:
            candidates.append(
                {
                    "url": gfav,
                    "type": "google_favicon",
                    "width": 256,
                    "height": 256,
                }
            )

    # Score and rank all discovered candidates
    candidates = sorted(
        candidates,
        key=lambda c: get_logo_candidate_score(
            c["url"], c["type"], c.get("width", 0), c.get("height", 0)
        ),
        reverse=True,
    )
    for c in candidates:
        if (
            get_logo_candidate_score(
                c["url"], c["type"], c.get("width", 0), c.get("height", 0)
            )
            > 0
        ):
            if validate_logo_image(c["url"]):
                return name, c["url"], f"ENRICHED_{c['type'].upper()}"

    if current_logo and validate_logo_image(current_logo):
        return name, current_logo, "EXISTS_VALID"

    return name, "", "NOT_FOUND"


async def enrich_logos_workflow(
    db_path=None,
    profile_dir=None,
    port=9334,
    resume_index=0,
    limit=None,
    force_upgrade=False,
    missing_only=False,
):
    """Asynchronous Chrome CDP + HTTP workflow to enrich high quality logos across database."""
    if db_path is None:
        db_path = os.environ.get(
            "STARTUP_DB_PATH",
            os.path.join(PROJECT_ROOT, "backend", "startups.json"),
        )
    if profile_dir is None:
        profile_dir = os.path.expanduser("~/starup_visualizer/chrome_profile_guest")

    print(f"Loading startups database from: {db_path}")
    with open(db_path, "r", encoding="utf-8") as f:
        startups = json.load(f)

    print(
        f"Preparing Chrome CDP crawling engine (Guest / No-Login Mode): {profile_dir} (Port"
        f" {port})"
    )
    chrome_proc = None
    ws_page = None
    target_id = None
    ws_browser_url = None

    if websockets and os.path.exists(
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    ):
        os.makedirs(profile_dir, exist_ok=True)
        chrome_proc = subprocess.Popen(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                f"--remote-debugging-port={port}",
                "--remote-allow-origins=*",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            ws_browser_url = await get_ws_browser_url(port=port)
            if ws_browser_url:
                print("[Chrome CDP] Connected to Chrome Debugging WebSocket!")
                async with websockets.connect(ws_browser_url, max_size=None) as ws:
                    cmd = {
                        "id": 1,
                        "method": "Target.createTarget",
                        "params": {"url": "about:blank"},
                    }
                    await ws.send(json.dumps(cmd))
                    res_create = json.loads(await ws.recv())
                    target_id = res_create.get("result", {}).get("targetId")
                if target_id:
                    ws_page = await websockets.connect(
                        f"ws://127.0.0.1:{port}/devtools/page/{target_id}",
                        max_size=None,
                    )
                    print(
                        f"[Chrome CDP] Created reusable page target tab: {target_id}"
                    )
        except Exception as e:
            print(f"[Chrome CDP] Failed to connect to debugger ({e}), falling back to HTTP engine.")

    if not ws_page:
        print("[Notice] Running via HTTP requests engine (Chrome CDP unavailable or offline).")

    enriched_count = 0
    processed_count = 0

    try:
        for idx, startup in enumerate(startups):
            if idx < resume_index:
                continue
            if limit and processed_count >= limit:
                print(f"Reached processing limit of {limit} startups.")
                break

            name = str(startup.get("name") or "Unknown").strip()
            web = str(startup.get("website") or "").strip()
            current_logo = str(startup.get("logo_svg_url") or "").strip()
            domain = extract_domain(web) or str(startup.get("logo_domain") or "").strip()

            # Ensure logo_domain is populated cleanly
            if domain and domain != startup.get("logo_domain", "") and not is_blacklisted_domain(domain):
                startup["logo_domain"] = domain

            # Check if company already has a logo
            if missing_only and current_logo and current_logo.startswith("http") and validate_logo_image(current_logo):
                processed_count += 1
                continue

            current_score = (
                get_logo_candidate_score(current_logo, "existing")
                if current_logo
                else 0
            )
            if not force_upgrade and not missing_only and current_score >= 95 and validate_logo_image(current_logo):
                # Already highest quality
                processed_count += 1
                continue

            print(
                f"\n[{idx+1}/{len(startups)}] Enriching logo for: {name} (Current:"
                f" '{current_logo[:35]}...')"
            )
            candidates = []

            # 1. Check LinkedIn company profile via Chrome CDP if slug exists
            ln_slug = extract_linkedin_slug(startup)
            if ws_page and ln_slug and not is_blacklisted_domain(ln_slug):
                ln_url = f"https://www.linkedin.com/company/{ln_slug}"
                print(f"  -> Crawling LinkedIn Profile: {ln_url}")
                ln_cands = await extract_candidates_via_chrome(
                    ws_page, ln_url, page_type="linkedin"
                )
                candidates.extend(ln_cands)
                await asyncio.sleep(random.uniform(1.5, 3.0))

            # 2. Check Official Homepage via Chrome CDP (or HTTP fallback)
            if web and not is_blacklisted_domain(web) and web.startswith(("http://", "https://")):
                print(f"  -> Crawling Official Homepage: {web}")
                if ws_page:
                    web_cands = await extract_candidates_via_chrome(
                        ws_page, web, page_type="website"
                    )
                    candidates.extend(web_cands)
                candidates.extend(extract_candidates_via_http(web))
                await asyncio.sleep(random.uniform(1.0, 2.0))

            # 3. Fallback high-res APIs
            if domain and not is_blacklisted_domain(domain):
                unav = check_unavatar_api(domain)
                if unav:
                    candidates.append(
                        {
                            "url": unav,
                            "type": "unavatar",
                            "width": 0,
                            "height": 0,
                        }
                    )
                gfav = check_google_favicon_api(domain)
                if gfav:
                    candidates.append(
                        {
                            "url": gfav,
                            "type": "google_favicon",
                            "width": 256,
                            "height": 256,
                        }
                    )

            # Sort by highest quality score
            candidates = sorted(
                candidates,
                key=lambda c: get_logo_candidate_score(
                    c["url"], c["type"], c.get("width", 0), c.get("height", 0)
                ),
                reverse=True,
            )
            selected_logo = None
            selected_type = None

            for c in candidates:
                cand_url = c["url"]
                cand_type = c["type"]
                cand_score = get_logo_candidate_score(
                    cand_url,
                    cand_type,
                    c.get("width", 0),
                    c.get("height", 0),
                )
                if cand_score > current_score and validate_logo_image(cand_url):
                    selected_logo = cand_url
                    selected_type = cand_type
                    break

            if selected_logo and selected_logo != startup.get("logo_svg_url", ""):
                print(
                    f"  [ENRICHED - {selected_type.upper()}] New High-Res Logo:"
                    f" {selected_logo}"
                )
                startup["logo_svg_url"] = selected_logo
                enriched_count += 1
            else:
                print("  [OK] Retaining existing logo or no superior candidate found.")

            processed_count += 1
            if processed_count % 10 == 0:
                with open(db_path, "w", encoding="utf-8") as f:
                    json.dump(startups, f, indent=2)

    finally:
        if ws_page:
            try:
                await ws_page.close()
            except Exception:
                pass
        if target_id and ws_browser_url:
            try:
                async with websockets.connect(
                    ws_browser_url, max_size=None
                ) as ws_b:
                    await ws_b.send(
                        json.dumps(
                            {
                                "id": 99,
                                "method": "Target.closeTarget",
                                "params": {"targetId": target_id},
                            }
                        )
                    )
            except Exception:
                pass

        if chrome_proc:
            print("Closing Google Chrome debugging session...")
            chrome_proc.terminate()
            chrome_proc.wait()

        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(startups, f, indent=2)
        print("\n=== HIGH-QUALITY LOGO ENRICHMENT COMPLETED ===")
        print(
            f"Total startups processed: {processed_count} | Logos enriched/upgraded:"
            f" {enriched_count}"
        )

        public_db_path = os.path.join(
            PROJECT_ROOT, "public", "static", "data", "startups.json"
        )
        os.makedirs(os.path.dirname(public_db_path), exist_ok=True)
        shutil.copy2(db_path, public_db_path)
        print(f"Synchronized database to: {public_db_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="High-Quality Logo Enricher using Chrome CDP with Login Profile"
    )
    parser.add_argument("--db-path", type=str, default=None, help="Path to startups database JSON")
    parser.add_argument("--profile-dir", type=str, default=None, help="Path to Chrome user data profile directory")
    parser.add_argument("--port", type=int, default=9334, help="Chrome remote debugging port")
    parser.add_argument("--resume-index", type=int, default=0, help="Index of startup in DB to resume from")
    parser.add_argument("--limit", type=int, default=None, help="Max startups to process")
    parser.add_argument("--force-upgrade", action="store_true", help="Crawl and check for higher quality logos even for startups that already have a valid logo")
    parser.add_argument("--missing-only", action="store_true", help="Only process startups that currently do not have any logo")
    parser.add_argument("--http-only", action="store_true", help="Bypass Chrome CDP and run in synchronous multi-threaded HTTP fallback mode")
    args = parser.parse_args()

    if args.http_only:
        print("Running in synchronous HTTP thread-pool fallback mode...")
        db_path = args.db_path or os.path.join(PROJECT_ROOT, "backend", "startups.json")
        with open(db_path, "r", encoding="utf-8") as f:
            startups = json.load(f)
        enriched_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
            results = list(executor.map(extract_official_logo, startups))
        res_map = {r[0]: (r[1], r[2]) for r in results}
        for s in startups:
            name = s.get("name")
            if name in res_map:
                logo_url, status = res_map[name]
                if logo_url and logo_url != s.get("logo_svg_url", ""):
                    s["logo_svg_url"] = logo_url
                    enriched_count += 1
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(startups, f, indent=2)
        print(f"[HTTP Mode] Enriched logos for {enriched_count} startups.")
        public_db_path = os.path.join(PROJECT_ROOT, "public", "static", "data", "startups.json")
        os.makedirs(os.path.dirname(public_db_path), exist_ok=True)
        shutil.copy2(db_path, public_db_path)
    else:
        asyncio.run(
            enrich_logos_workflow(
                db_path=args.db_path,
                profile_dir=args.profile_dir,
                port=args.port,
                resume_index=args.resume_index,
                limit=args.limit,
                force_upgrade=args.force_upgrade,
                missing_only=args.missing_only,
            )
        )


if __name__ == "__main__":
    main()
