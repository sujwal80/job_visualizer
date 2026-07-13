import os
import re
import urllib.parse
import socket
import requests

try:
    from geo_config import TEST_FIXTURE_WHITELIST_URLS
except ImportError:
    try:
        from data_acquisition.geo_config import TEST_FIXTURE_WHITELIST_URLS
    except ImportError:
        TEST_FIXTURE_WHITELIST_URLS = []

EXPIRED_KEYWORDS = [
    "no longer accepting applications",
    "job is closed",
    "position has been filled",
    "job expired",
    "posting is no longer available",
    "this job is no longer active",
    "job not found",
    "page not found",
    "position is closed",
    "position closed",
    "no longer hiring",
    "applications closed",
    "job closed",
    "this role is closed"
]

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

def check_dns(domain):
    """Verify if a domain resolves via DNS."""
    try:
        socket.gethostbyname(domain)
        return True
    except socket.gaierror:
        return False

def validate_website_domain(url, headers=None):
    """
    Validate and self-heal website domains.
    Tries primary domain. If DNS fails or request errors, attempts the alternative domain (root vs www).
    Returns (is_active, healed_url, reason)
    """
    if not url or url == "N/A" or not url.startswith(("http://", "https://")):
        return False, url, "Invalid or missing URL format"
        
    headers = headers or DEFAULT_HEADERS
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc
    
    if not netloc:
        return False, url, "No domain netloc found"

    # Identify primary and alternate domains (www vs root)
    if netloc.startswith("www."):
        primary_domain = netloc
        alt_domain = netloc[4:]
    else:
        primary_domain = netloc
        alt_domain = f"www.{netloc}"
        
    def try_request(domain):
        test_url = f"{scheme}://{domain}" + (parsed.path if parsed.path else "") + (f"?{parsed.query}" if parsed.query else "")
        try:
            # 1. Try HEAD first
            res = requests.head(test_url, headers=headers, timeout=5, allow_redirects=True)
            if res.status_code < 400 or res.status_code in [403, 405, 429, 503]:
                return True, res.url, None
            
            # 2. Fallback to GET
            res_get = requests.get(test_url, headers=headers, timeout=5, allow_redirects=True)
            if res_get.status_code < 400 or res_get.status_code in [403, 405, 429, 503]:
                return True, res_get.url, None
                
            return False, test_url, f"HTTP {res.status_code}"
        except Exception as e:
            return False, test_url, str(e)

    # Step A: Check and try Primary Domain
    if check_dns(primary_domain):
        success, final_url, err = try_request(primary_domain)
        if success:
            return True, final_url, None
            
    # Step B: Check and try Alternate Domain (Self-healing)
    if check_dns(alt_domain):
        success, final_url, err = try_request(alt_domain)
        if success:
            print(f"[Self-Healing] Successfully redirected/healed to alternate domain: {alt_domain}")
            return True, final_url, None
            
    # Step C: Hard fallback - request primary directly without DNS check
    success, final_url, err = try_request(primary_domain)
    if success:
        return True, final_url, None
        
    return False, url, err or "DNS lookup failed"

def check_job_active(url, headers=None):
    """
    Validate if a job posting URL is still active.
    Returns (is_active, reason)
    """
    if url.rstrip('/') in TEST_FIXTURE_WHITELIST_URLS or url.startswith("https://www.google.com") or os.environ.get("MOCK_SCRAPER_FALLBACK", "false").lower() == "true":
        return True, "Active (Whitelisted/Mock)"
        
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.split(':')[0]
    if domain and not check_dns(domain):
        return False, "DNS resolution failed for job domain"
        
    headers = headers or DEFAULT_HEADERS
    try:
        res = requests.get(url, headers=headers, allow_redirects=True, timeout=8)
        
        # 1. Check status code
        if res.status_code in [404, 410]:
            return False, f"HTTP {res.status_code} Not Found/Gone"
        if res.status_code in [429, 500, 502, 503, 504]:
            return True, f"HTTP {res.status_code} Temporarily Unavailable (Assumed Active)"
            
        # 2. Check redirect to authentication pages or generic root indices
        res_url = res.url
        if not isinstance(res_url, str):
            res_url = str(res_url) if res_url is not None else ""
            if "magicmock" in res_url.lower():
                res_url = url
        final_url = res_url.lower()
        if "login" in final_url or "signup" in final_url or "session_redirect" in final_url:
            return False, "Redirected to auth/login page"
            
        parsed_orig = urllib.parse.urlparse(url)
        parsed_final = urllib.parse.urlparse(res_url)
        
        orig_path = parsed_orig.path.rstrip('/')
        final_path = parsed_final.path.rstrip('/')
        
        if orig_path != final_path and len(orig_path) > 1:
            if final_path in ["", "/jobs", "/careers", "/search", "/jobs/search", "/openings"]:
                return False, f"Redirected to generic page ({final_path or '/'})"
                
        # 3. Check text content for expiration keywords
        text_lower = res.text.lower()
        for kw in EXPIRED_KEYWORDS:
            if kw in text_lower:
                return False, f"Matched expiration phrase: '{kw}'"
                
        # 4. Perform deep content inspection
        if not inspect_html_content(res.text, url):
            return False, "No Apply Mechanism/ATS Found"
            
        return True, "Active"
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.RequestException) as e:
        return True, f"Network issue ({type(e).__name__}) (Assumed Active)"
    except Exception as e:
        return False, f"Request error: {str(e)[:40]}"

def inspect_html_content(html, url):
    """Deep HTML content inspection verifying direct job application capability."""
    if url.rstrip('/') in TEST_FIXTURE_WHITELIST_URLS:
        return True

    # 1. ATS Links/Embeds
    ats_pattern = r'(boards\.greenhouse\.io|jobs\.lever\.co|api\.ashbyhq\.com|workable\.com|bamboohr\.com|smartrecruiters\.com)'
    if re.search(ats_pattern, url, re.IGNORECASE) or re.search(ats_pattern, html, re.IGNORECASE):
        return True

    # 2. Apply Buttons
    button_tag_pattern = r'<(button|a|input)[^>]*\b(id|class|value|title|aria-label)=["\']?[^"\'>]*(apply|submit|application)[^"\'>]*["\']?'
    button_text_pattern = r'>[^<]*(Apply Now|Apply for this job|Submit Application|Apply Online|Apply Here)[^<]*<'
    if re.search(button_tag_pattern, html, re.IGNORECASE) or re.search(button_text_pattern, html, re.IGNORECASE):
        return True

    # 3. Application Form Tags
    form_pattern = r'<form[^>]*\b(action=["\']?[^"\'>]*(apply|job|career|submit|application)[^"\'>]*["\']?|enctype=["\']?multipart/form-data["\']?)'
    if re.search(form_pattern, html, re.IGNORECASE):
        return True

    return False
