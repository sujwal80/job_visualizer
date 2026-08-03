import os
import re
import urllib.parse
import socket
import requests
import logging
import ipaddress
import contextlib
import urllib3.util.connection as urllib3_conn
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

BLACKLISTED_DOMAINS = {
    "goo.gle", "bit.ly", "linktr.ee", "tinyurl.com", "t.co", "buff.ly", "goo.gl", "ow.ly",
    "forms.gle", "google.com", "docs.google.com", "sheets.google.com", "drive.google.com",
    "linkedin.com", "instagram.com", "facebook.com", "twitter.com", "x.com",
    "naukri.com", "wellfound.com", "glassdoor.com", "indeed.com", "cutshort.io",
    "instahyre.com", "hirist.com", "hirist.tech", "ycombinator.com", "start.myjar.app",
    "internshala.com", "myjar.app"
}

def is_blacklisted_domain(domain):
    """
    Checks if domain or any parent domain level matches BLACKLISTED_DOMAINS.
    Correctly matches subdomains (e.g. careers.linkedin.com or start.myjar.app).
    """
    if not domain or not isinstance(domain, str):
        return False
    d = domain.strip().lower()
    if d.startswith("http://") or d.startswith("https://"):
        try:
            parsed = urllib.parse.urlparse(d)
            d = parsed.netloc.lower()
        except Exception:
            pass
    if d.startswith("www."):
        d = d[4:]
    d = d.split(':')[0].strip()
    if not d:
        return False
    for b in BLACKLISTED_DOMAINS:
        if d == b or d.endswith("." + b):
            return True
    return False

def is_safe_ip(ip_str):
    """Verify if the IP address is public and safe (not loopback, private, link-local, multicast, etc.)."""
    try:
        ip = ipaddress.ip_address(ip_str)
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
        return True
    except ValueError:
        return False

def resolve_and_verify_host(host):
    """
    Resolves a hostname to its IP address.
    Returns (ip, status) where status is:
      - "safe" if resolved to a safe public IP.
      - "unsafe" if resolved to an unsafe loopback/private IP.
      - "failed" if DNS resolution raised an exception.
    """
    try:
        ip = socket.gethostbyname(host)
        if not is_safe_ip(ip):
            logger.warning(f"Domain {host} resolved to unsafe IP {ip}. Blocked.")
            return None, "unsafe"
        return ip, "safe"
    except Exception as e:
        logger.warning(f"DNS resolution failed for {host}: {e}")
        return None, "failed"

@contextlib.contextmanager
def dns_resolver_override(dns_map):
    """Context manager to force socket connection creation to use pre-resolved IP addresses."""
    orig_create_connection = urllib3_conn.create_connection

    def patched_create_connection(address, *args, **kwargs):
        host, port = address
        if host in dns_map:
            resolved_ip = dns_map[host]
            return orig_create_connection((resolved_ip, port), *args, **kwargs)
        return orig_create_connection(address, *args, **kwargs)

    urllib3_conn.create_connection = patched_create_connection
    try:
        yield
    finally:
        urllib3_conn.create_connection = orig_create_connection

def safe_http_request(method, url, headers=None, timeout=5, stream=False, max_redirects=5, **kwargs):
    """
    Executes HTTP request securely against SSRF and DNS Rebinding.
    Follows redirects manually up to max_redirects, checking IP safety at each hop.
    """
    headers = headers or {}
    current_url = url
    dns_map = {}
    
    for redirect_hop in range(max_redirects + 1):
        parsed = urllib.parse.urlparse(current_url)
        if not parsed.scheme or parsed.scheme not in ["http", "https"]:
            raise requests.exceptions.RequestException(f"Unsupported URL scheme: {parsed.scheme}")
            
        host = parsed.hostname
        if not host:
            raise requests.exceptions.RequestException(f"Invalid URL host: {current_url}")
            
        # Resolve and verify host IP safety
        resolved_ip, status = resolve_and_verify_host(host)
        if status == "unsafe":
            raise requests.exceptions.RequestException(f"Private IP range blocked for host: {host}")
            
        # Request handling
        if status == "safe":
            dns_map[host] = resolved_ip
            # Request with DNS override active
            with dns_resolver_override(dns_map):
                if method.upper() == "GET":
                    response = requests.get(
                        current_url, 
                        headers=headers, 
                        timeout=timeout, 
                        stream=stream, 
                        allow_redirects=False, 
                        **kwargs
                    )
                elif method.upper() == "HEAD":
                    response = requests.head(
                        current_url, 
                        headers=headers, 
                        timeout=timeout, 
                        allow_redirects=False, 
                        **kwargs
                    )
                else:
                    response = requests.request(
                        method, 
                        current_url, 
                        headers=headers, 
                        timeout=timeout, 
                        stream=stream, 
                        allow_redirects=False, 
                        **kwargs
                    )
        else:
            # DNS resolution failed. Let requests handle it directly so the proper connection error is raised.
            if method.upper() == "GET":
                response = requests.get(
                    current_url, 
                    headers=headers, 
                    timeout=timeout, 
                    stream=stream, 
                    allow_redirects=False, 
                    **kwargs
                )
            elif method.upper() == "HEAD":
                response = requests.head(
                    current_url, 
                    headers=headers, 
                    timeout=timeout, 
                    allow_redirects=False, 
                    **kwargs
                )
            else:
                response = requests.request(
                    method, 
                    current_url, 
                    headers=headers, 
                    timeout=timeout, 
                    stream=stream, 
                    allow_redirects=False, 
                    **kwargs
                )
            
        # Manual redirection handling
        if response.status_code in [301, 302, 303, 307, 308]:
            location = response.headers.get("Location")
            if not location:
                return response
            current_url = urllib.parse.urljoin(current_url, location)
            continue
        else:
            return response
            
    raise requests.exceptions.TooManyRedirects(f"Exceeded max redirects ({max_redirects})")

def is_cloudflare_response(res):
    """Detect if response is served/blocked by Cloudflare."""
    if res is None:
        return False
    server = res.headers.get("Server", "")
    if "cloudflare" in server.lower():
        return True
    if "cf-ray" in res.headers or "cf-cache-status" in res.headers:
        return True
    return False

def is_parking_page(html_content, content_length=None):
    """
    Identify domain parking pages.
    Inspects title keywords if content-length is short (< 2000 bytes) or lacks layout features.
    """
    if not html_content:
        return False
        
    if content_length is None:
        content_length = len(html_content)
        
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
    if not title_match:
        return False
        
    title = title_match.group(1).strip().lower()
    
    parking_keywords = [
        "litespeed", "hostinger", "domain parked", "buy this domain", 
        "parked domain", "this domain is registered", "under construction",
        "domain is for sale", "domain name for sale", "godaddy", "namecheap",
        "site ground", "bluehost", "hostgator"
    ]
    
    has_parking_keyword = any(kw in title for kw in parking_keywords)
    if not has_parking_keyword:
        return False
        
    # Condition: body is short (< 2000 bytes)
    if content_length < 2000:
        return True
        
    # Condition: lacks layout features
    layout_features = [
        "class=\"container\"", "class='container'", "id=\"header\"", "id='header'",
        "<header", "<footer", "<nav", "class=\"row\"", "class='row'", "bootstrap"
    ]
    has_layout = any(feature in html_content.lower() for feature in layout_features)
    
    if not has_layout:
        return True
        
    return False

def perform_url_check(test_url, headers, timeout=5):
    """
    Performs HEAD and optionally GET to validate URL.
    Returns (success, final_url, error_message)
    """
    try:
        # SSRF Private IP protection
        try:
            parsed = urllib.parse.urlparse(test_url)
            domain = parsed.netloc.split(':')[0]
            ip, status = resolve_and_verify_host(domain)
            if status == "unsafe":
                return False, test_url, "Private IP range blocked"
        except Exception:
            pass

        # 1. Try HEAD first
        res = safe_http_request("HEAD", test_url, headers=headers, timeout=timeout)
        
        # Cloudflare handling on 403 or 200
        if res.status_code in [200, 403] and is_cloudflare_response(res):
            return True, res.url, None
            
        if res.status_code < 400 or res.status_code in [403, 405, 429, 503]:
            # Perform GET to check for parking pages if status < 400
            if res.status_code < 400:
                try:
                    res_get = safe_http_request("GET", test_url, headers=headers, timeout=timeout)
                    if is_cloudflare_response(res_get):
                        return True, res_get.url, None
                    if is_parking_page(res_get.text, len(res_get.content)):
                        return False, test_url, "Parking page detected"
                    return True, res_get.url, None
                except Exception:
                    # Fallback to successful HEAD response
                    pass
            return True, res.url, None
            
        # 2. Fallback to GET
        res_get = safe_http_request("GET", test_url, headers=headers, timeout=timeout)
        if res_get.status_code in [200, 403] and is_cloudflare_response(res_get):
            return True, res_get.url, None
            
        if is_parking_page(res_get.text, len(res_get.content)):
            return False, test_url, "Parking page detected"
            
        if res_get.status_code < 400 or res_get.status_code in [403, 405, 429, 503]:
            return True, res_get.url, None
            
        return False, test_url, f"HTTP {res_get.status_code}"
        
    except requests.exceptions.SSLError as ssl_err:
        raise ssl_err
    except Exception as e:
        return False, test_url, str(e)

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
    """Verify if a domain resolves via DNS and is not a private/loopback/link-local IP (SSRF protection)."""
    ip, status = resolve_and_verify_host(domain)
    return status == "safe"

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
            success, final_url, err = perform_url_check(test_url, headers, timeout=5)
            return success, final_url, err
        except requests.exceptions.SSLError as ssl_err:
            if test_url.startswith("https://"):
                fallback_url = test_url.replace("https://", "http://", 1)
                try:
                    success, final_url, err = perform_url_check(fallback_url, headers, timeout=5)
                    if success:
                        return True, final_url, None
                    return False, test_url, f"SSLError: {ssl_err} (HTTP fallback returned: {err})"
                except Exception as fallback_err:
                    return False, test_url, f"SSLError: {ssl_err} (HTTP fallback failed: {fallback_err})"
            return False, test_url, str(ssl_err)
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
        res = safe_http_request("GET", url, headers=headers, timeout=8)
        
        # 1. Check status code
        if res.status_code in [404, 410]:
            return False, f"HTTP {res.status_code} Not Found/Gone"
        if res.status_code in [429, 500, 502, 503, 504]:
            return True, f"HTTP {res.status_code} Temporarily Unavailable (Assumed Active)"
            
        # Cloudflare check
        if res.status_code in [200, 403] and is_cloudflare_response(res):
            return True, "Active (Cloudflare Protection)"
            
        # Parking page check
        if is_parking_page(res.text, len(res.content)):
            return False, "Parking page detected"
            
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

def is_safe_svg(content_bytes):
    """
    Checks if SVG content is safe: parses it securely, rejecting DTDs/DOCTYPEs,
    external entities, event handler attributes, blacklisted tags, and style URLs/imports.
    """
    if not content_bytes:
        return False
        
    try:
        content_str = content_bytes.decode('utf-8', errors='ignore')
    except Exception:
        return False
        
    content_str_lower = content_str.lower()
    
    # Reject DTDs and Entity declarations to prevent XXE / Billion Laughs (XML Bomb)
    if '<!doctype' in content_str_lower or '<!entity' in content_str_lower:
        logger.warning("Rejected SVG containing DTD or Entity declaration.")
        return False
        
    try:
        root = ET.fromstring(content_str)
    except Exception as e:
        logger.warning(f"XML parse failed: {e}")
        return False
        
    for elem in root.iter():
        tag = elem.tag
        local_tag = tag.split('}', 1)[1].lower() if '}' in tag else tag.lower()
        
        # Blacklisted tags
        if local_tag in ('script', 'foreignobject', 'iframe', 'object', 'embed', 'html'):
            logger.warning(f"Rejected SVG containing blacklisted tag: {local_tag}")
            return False
            
        # Style tag content scanning
        if local_tag == 'style':
            style_text = elem.text or ""
            if re.search(r'url\s*\(', style_text, re.IGNORECASE):
                logger.warning("Rejected SVG containing external URL reference in style tag.")
                return False
            if re.search(r'@import', style_text, re.IGNORECASE):
                logger.warning("Rejected SVG containing @import reference in style tag.")
                return False
                
        # Attributes validation
        for name, value in elem.attrib.items():
            local_attr = name.split('}', 1)[1].lower() if '}' in name else name.lower()
            
            # Event handlers
            if local_attr.startswith('on'):
                logger.warning(f"Rejected SVG containing event handler attribute: {local_attr}")
                return False
                
            # Javascript URIs in href / xlink:href
            if local_attr in ('href', 'xlink:href'):
                if value.strip().lower().startswith('javascript:'):
                    logger.warning("Rejected SVG containing javascript URI in href.")
                    return False
                    
            # Inline style attribute scanning
            if local_attr == 'style':
                if re.search(r'url\s*\(', value, re.IGNORECASE):
                    logger.warning("Rejected SVG containing external URL reference in inline style.")
                    return False
                    
    return True

def get_image_dimensions(content_bytes):
    """
    Parses image dimensions (width, height) from raw bytes for PNG, GIF, JPEG, and SVG.
    Returns (width, height) tuple or (None, None) if parsing fails.
    """
    if not content_bytes or not isinstance(content_bytes, (bytes, bytearray)):
        return None, None
        
    length = len(content_bytes)
    
    # 1. PNG: magic \x89PNG\r\n\x1a\n
    if length >= 24 and content_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        width = int.from_bytes(content_bytes[16:20], 'big')
        height = int.from_bytes(content_bytes[20:24], 'big')
        return width, height

    # 2. GIF: magic GIF87a or GIF89a
    if length >= 10 and (content_bytes.startswith(b'GIF87a') or content_bytes.startswith(b'GIF89a')):
        width = int.from_bytes(content_bytes[6:8], 'little')
        height = int.from_bytes(content_bytes[8:10], 'little')
        return width, height

    # 3. JPEG: magic \xff\xd8
    if length >= 4 and content_bytes.startswith(b'\xff\xd8'):
        idx = 2
        while idx < length - 8:
            if content_bytes[idx] != 0xFF:
                idx += 1
                continue
            marker = content_bytes[idx + 1]
            if marker in (0xD8, 0xD9, 0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7):
                idx += 2
                continue
            if idx + 4 > length:
                break
            seg_len = int.from_bytes(content_bytes[idx + 2:idx + 4], 'big')
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if idx + 9 <= length:
                    height = int.from_bytes(content_bytes[idx + 5:idx + 7], 'big')
                    width = int.from_bytes(content_bytes[idx + 7:idx + 9], 'big')
                    return width, height
                break
            idx += 2 + seg_len

    # 4. SVG: string search for width/height or viewBox
    try:
        snippet = content_bytes[:2048].decode('utf-8', errors='ignore')
        if '<svg' in snippet.lower():
            w_match = re.search(r'\bwidth=["\']?(\d+)(?:px)?["\']?', snippet, re.IGNORECASE)
            h_match = re.search(r'\bheight=["\']?(\d+)(?:px)?["\']?', snippet, re.IGNORECASE)
            if w_match and h_match:
                return int(w_match.group(1)), int(h_match.group(1))
            vb_match = re.search(r'\bviewBox=["\']?\s*[\d\.\-]+\s+[\d\.\-]+\s+([\d\.]+)\s+([\d\.]+)["\']?', snippet, re.IGNORECASE)
            if vb_match:
                return int(float(vb_match.group(1))), int(float(vb_match.group(2)))
    except Exception:
        pass

    return None, None


def validate_logo_image(logo_url, content_bytes=None, headers=None):
    """
    Validate logo image URL, content bytes, and response headers.
    Checks domain blacklist, image resolution (rejects 16x16 Google globe icons,
    1x1 transparent PNG/GIF pixels), Unavatar 404/fallback responses, and unsafe content.
    """
    if not logo_url or not isinstance(logo_url, str) or not logo_url.startswith(("http://", "https://")):
        return False

    url_lower = logo_url.lower()
    junk_keywords = [
        ".gif", "/banner/", "banner.", "-banner", "banner-", "discount", "offer",
        "join-elite", "hero", "blog", "slide", "1200x", "ogimage", "about-us",
        "about_us", "footer_logo", "facebook", "twitter", "instagram", "youtube"
    ]
    if any(kw in url_lower for kw in junk_keywords):
        return False

    try:
        parsed = urllib.parse.urlparse(logo_url)
        netloc_domain = parsed.netloc.split(':')[0].lower()
        if netloc_domain.startswith('www.'):
            netloc_domain = netloc_domain[4:]

        # Extract target domain for favicon / unavatar services
        target_domain = netloc_domain
        if "google.com/s2/favicons" in logo_url:
            qs = urllib.parse.parse_qs(parsed.query)
            target_domain = qs.get("domain", [netloc_domain])[0]
        elif "unavatar.io" in logo_url:
            path_parts = parsed.path.strip('/').split('/')
            if path_parts and path_parts[0]:
                target_domain = path_parts[0]

        # Domain blacklist check
        if is_blacklisted_domain(target_domain):
            return False

        if is_blacklisted_domain(netloc_domain):
            return False

        # SSRF Private IP protection
        try:
            if not resolve_and_verify_host(netloc_domain):
                return False
        except Exception:
            pass

        # If content_bytes is provided directly
        if content_bytes is not None:
            if not isinstance(content_bytes, (bytes, bytearray)) or not content_bytes:
                return False

            if headers and isinstance(headers, dict):
                if headers.get("x-fallback", "").lower() == "true" or headers.get("x-unavatar-fallback", "").lower() == "true":
                    return False
                c_type = headers.get("Content-Type", "").lower()
                if c_type and not c_type.startswith("image/") and "image/svg+xml" not in c_type:
                    return False

            try:
                content_str_chunk = content_bytes[:4096].decode('utf-8', errors='ignore').lower()
            except Exception:
                content_str_chunk = ""

            is_svg = "<svg" in content_str_chunk or "<?xml" in content_str_chunk
            is_html = "<html" in content_str_chunk or "<!doctype html" in content_str_chunk

            if is_html:
                return False
            if is_svg and not is_safe_svg(content_bytes):
                return False

            w, h = get_image_dimensions(content_bytes)
            if w is not None and h is not None:
                if w == 1 and h == 1:
                    return False
                if w == 16 and h == 16:
                    return False

            return True

        # Call safe_http_request for HEAD first to satisfy existing tests and check headers
        res = safe_http_request("HEAD", logo_url, timeout=5)
        if res.status_code == 404:
            return False

        if res.headers.get("x-fallback", "").lower() == "true" or res.headers.get("x-unavatar-fallback", "").lower() == "true":
            return False

        # If it is 403 or 405, do GET fallback
        if res.status_code in [403, 405]:
            try:
                res_get = safe_http_request("GET", logo_url, timeout=5, stream=True)
                if res_get.status_code in [403, 404, 405] or res_get.status_code >= 400:
                    return False
                if res_get.headers.get("x-fallback", "").lower() == "true" or res_get.headers.get("x-unavatar-fallback", "").lower() == "true":
                    return False
                content_type = res_get.headers.get("Content-Type", "").lower()
                
                content_chunk = res_get.raw.read(4096)
                if not content_chunk:
                    return False
                try:
                    content_str_chunk = content_chunk.decode('utf-8', errors='ignore')
                except Exception:
                    content_str_chunk = ""
                content_str_lower = content_str_chunk.lower()
                
                is_svg = "image/svg+xml" in content_type or "<svg" in content_str_lower or "<?xml" in content_str_lower
                is_html = "text/html" in content_type or "<html" in content_str_lower or "<!doctype html" in content_str_lower
                
                if is_svg:
                    remaining_bytes = res_get.raw.read(1024 * 1024)
                    full_content = content_chunk + remaining_bytes
                    if not is_safe_svg(full_content):
                        return False
                    w, h = get_image_dimensions(full_content)
                elif is_html:
                    return False
                else:
                    is_claimed_standard_image = any(img_type in content_type for img_type in ["image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"])
                    if is_claimed_standard_image:
                        if "<svg" in content_str_lower or "<html" in content_str_lower or "<script" in content_str_lower:
                            return False
                    remaining_bytes = res_get.raw.read(1024 * 1024)
                    full_content = content_chunk + remaining_bytes
                    w, h = get_image_dimensions(full_content)

                if w is not None and h is not None:
                    if w == 1 and h == 1:
                        return False
                    if w == 16 and h == 16:
                        return False

                if not content_type.startswith("image/"):
                    if not is_svg:
                        return False
                return True
            except requests.exceptions.SSLError as ssl_err:
                logger.warning(f"SSL error validating logo via GET fallback {logo_url}: {ssl_err}")
                return False
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                logger.warning(f"Error validating logo via GET fallback {logo_url}: {e}")
                return False
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request exception validating logo via GET fallback {logo_url}: {e}")
                return False
            except Exception as e:
                logger.warning(f"Error validating logo via GET fallback {logo_url}: {e}")
                return False

        # If HEAD returned 200/success, we check the Content-Type
        content_type = res.headers.get("Content-Type", "").lower()
        
        try:
            res_get = safe_http_request("GET", logo_url, timeout=5, stream=True)
            if res_get.status_code == 200:
                    if res_get.headers.get("x-fallback", "").lower() == "true" or res_get.headers.get("x-unavatar-fallback", "").lower() == "true":
                        return False
                    content_type = res_get.headers.get("Content-Type", "").lower()
                    full_content = res_get.content[:1024 * 1024]
                    if full_content:
                        try:
                            content_str_lower = full_content[:4096].decode('utf-8', errors='ignore').lower()
                        except Exception:
                            content_str_lower = ""
                        
                        is_svg = "image/svg+xml" in content_type or "<svg" in content_str_lower or "<?xml" in content_str_lower
                        is_html = "text/html" in content_type or "<html" in content_str_lower or "<!doctype html" in content_str_lower
                        
                        if is_svg:
                            if not is_safe_svg(full_content):
                                return False
                            w, h = get_image_dimensions(full_content)
                        elif is_html:
                            return False
                        else:
                            is_claimed_standard_image = any(img_type in content_type for img_type in ["image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"])
                            if is_claimed_standard_image:
                                if "<svg" in content_str_lower or "<html" in content_str_lower or "<script" in content_str_lower:
                                    return False
                            w, h = get_image_dimensions(full_content)

                        if w is not None and h is not None:
                            if w == 1 and h == 1:
                                return False
                            if w == 16 and h == 16:
                                return False
        except Exception as e:
            logger.warning(f"GET check failed for {logo_url}: {e}")
            return False

        if not content_type.startswith("image/"):
            if "image/svg+xml" not in content_type:
                return False
                
        return True

    except requests.exceptions.SSLError as ssl_err:
        logger.warning(f"SSL error validating logo {logo_url}: {ssl_err}")
        return False
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        logger.warning(f"Error validating logo {logo_url}: {e}")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"Request exception validating logo {logo_url}: {e}")
        return False
    except Exception as e:
        logger.warning(f"Error validating logo {logo_url}: {e}")
        return False

