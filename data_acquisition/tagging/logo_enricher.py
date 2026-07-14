import urllib.parse
import re
import requests
from bs4 import BeautifulSoup
try:
    from data_acquisition.utils.validation import safe_http_request, validate_logo_image
except ImportError:
    from utils.validation import safe_http_request, validate_logo_image

BLACKLISTED_DOMAINS = {
    "bit.ly", "linktr.ee", "tinyurl.com", "t.co", "buff.ly", "goo.gl", "ow.ly",
    "forms.gle", "google.com", "docs.google.com", "sheets.google.com", "drive.google.com",
    "linkedin.com", "instagram.com", "facebook.com", "twitter.com", "x.com"
}

class LogoEnricher:
    """
    Independent tagging module for resolving company logo domains and SVG urls.
    Implements short-circuiting: if logo_domain is already known and logo_svg_url is
    present (even if empty), it skips processing.
    """
    def enrich(self, company_record):
        """
        Enriches company_record in-place.
        Returns True if modified, False if short-circuited or unchanged.
        """
        if not isinstance(company_record, dict):
            return False
            
        # Short-circuit and clear fields if website is dead
        if company_record.get("is_active_website") is False:
            if company_record.get("logo_svg_url") != "":
                company_record["logo_svg_url"] = ""
                return True
            return False
            
        name = str(company_record.get("name") or "").strip()
        website = str(company_record.get("website") or "").strip()
        if (not name or name == "N/A") and not website:
            return False
            
        modified = False
        
        # 1. Check and enrich logo_domain if missing/blacklisted
        current_domain = str(company_record.get("logo_domain") or "").strip()
        has_valid_domain = current_domain and current_domain.lower() not in BLACKLISTED_DOMAINS
        
        if not has_valid_domain:
            if website:
                extracted = self._extract_domain(website)
                if extracted and extracted not in BLACKLISTED_DOMAINS:
                    comp_name = str(company_record.get("name") or "N/A")
                    print(f"[Logo Enricher] Tagged logo domain '{extracted}' from website for '{comp_name}'")
                    company_record["logo_domain"] = extracted
                    modified = True
                    has_valid_domain = True
                    current_domain = extracted
                    
            if not has_valid_domain:
                # Fallback: Deduce candidate domain from company name
                name = str(company_record.get("name") or "").strip()
                if name and name != "N/A":
                    clean_name = re.sub(r'[^a-zA-Z0-9]', '', name).lower()
                    if clean_name:
                        candidate = f"{clean_name}.com"
                        print(f"[Logo Enricher] Tagged fallback logo domain '{candidate}' for '{name}'")
                        company_record["logo_domain"] = candidate
                        modified = True
                        has_valid_domain = True
                        current_domain = candidate
                        
        # 2. Check and enrich logo_svg_url if missing, empty, or invalid (does not start with http or fails validation)
        current_svg = str(company_record.get("logo_svg_url") or "").strip()
        is_valid_svg = current_svg.startswith("http")
        if is_valid_svg:
            if not validate_logo_image(current_svg):
                is_valid_svg = False
        
        if not is_valid_svg:
            logo_url = ""
            
            # Priority A: SVG Scraping
            if website:
                svg_url = self._scrape_svg_logo(website)
                if svg_url and validate_logo_image(svg_url):
                    logo_url = svg_url
            
            # Priority B: Unavatar API check (200 status code)
            if not logo_url and current_domain:
                unavatar_url = self._check_unavatar(current_domain)
                if unavatar_url and validate_logo_image(unavatar_url):
                    logo_url = unavatar_url
            
            # Priority C: Google Favicon API check (200 status code)
            if not logo_url and current_domain:
                google_url = self._check_google_favicon(current_domain)
                if google_url and validate_logo_image(google_url):
                    logo_url = google_url
            
            company_record["logo_svg_url"] = logo_url
            print(f"[Logo Enricher] Resolved logo URL '{logo_url}' for '{company_record.get('name')}'")
            modified = True
            
        return modified

    def _check_unavatar(self, domain):
        try:
            url = f"https://unavatar.io/{domain}?fallback=false"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = safe_http_request("GET", url, timeout=5, headers=headers)
            if resp.status_code == 200:
                return f"https://unavatar.io/{domain}"
            elif resp.status_code == 429:
                print(f"[Logo Enricher] Unavatar rate limit (429) for '{domain}' - falling back immediately")
        except Exception as e:
            print(f"[Logo Enricher] Error checking Unavatar for '{domain}': {e}")
        return None

    def _check_google_favicon(self, domain):
        try:
            url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = safe_http_request("GET", url, timeout=5, headers=headers)
            if resp.status_code == 200:
                return url
        except Exception as e:
            print(f"[Logo Enricher] Error checking Google Favicon for '{domain}': {e}")
        return None

    def _scrape_svg_logo(self, website_url):
        website_url = str(website_url or "").strip()
        if not website_url:
            return None
            
        if not website_url.startswith(('http://', 'https://')):
            website_url = 'https://' + website_url
            
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = safe_http_request("GET", website_url, timeout=5, headers=headers)
            if response.status_code != 200:
                return self._check_fallback_svg(website_url)
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            svg_href = None
            for link in soup.find_all('link'):
                rel = [r.lower() for r in (link.get('rel') or [])]
                href = link.get('href')
                if not href:
                    continue
                
                link_type = str(link.get('type') or "").lower().strip()
                is_svg_link = (link_type == "image/svg+xml" or 
                               href.lower().split('?')[0].endswith('.svg') or 
                               href.lower().split('#')[0].endswith('.svg'))
                
                if is_svg_link:
                    if any(r in rel for r in ['icon', 'shortcut icon', 'apple-touch-icon', 'apple-touch-icon-precomposed', 'mask-icon']):
                        svg_href = href
                        break
            
            if not svg_href:
                for link in soup.find_all('link'):
                    href = link.get('href')
                    if href and (href.lower().split('?')[0].endswith('.svg') or href.lower().split('#')[0].endswith('.svg')):
                        svg_href = href
                        break
                        
            if svg_href:
                return urllib.parse.urljoin(website_url, svg_href)
                
            return self._check_fallback_svg(website_url)
            
        except Exception as e:
            print(f"[Logo Enricher] Error scraping SVG for {website_url}: {e}")
            return self._check_fallback_svg(website_url)

    def _check_fallback_svg(self, base_url):
        try:
            parsed = urllib.parse.urlparse(base_url)
            root_url = f"{parsed.scheme}://{parsed.netloc}"
            favicon_url = urllib.parse.urljoin(root_url, "/favicon.svg")
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = safe_http_request("GET", favicon_url, timeout=5, headers=headers)
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "").lower()
                preview = resp.text[:1000].strip()
                if "svg" in content_type or "<svg" in preview.lower() or preview.startswith("<?xml"):
                    return favicon_url
        except Exception:
            pass
        return None

    def _extract_domain(self, url):
        try:
            url = str(url or "").strip()
            if not url:
                return ""
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            parsed = urllib.parse.urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain.split(':')[0]
        except Exception:
            return ""
