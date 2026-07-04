import urllib.parse
import re

BLACKLISTED_DOMAINS = {
    "bit.ly", "linktr.ee", "tinyurl.com", "t.co", "buff.ly", "goo.gl", "ow.ly",
    "forms.gle", "google.com", "docs.google.com", "sheets.google.com", "drive.google.com",
    "linkedin.com", "instagram.com", "facebook.com", "twitter.com", "x.com"
}

class LogoEnricher:
    """
    Independent tagging module for resolving company logo domains.
    Implements short-circuiting: if logo_domain is already known from acquisition,
    it skips processing.
    """
    def enrich(self, company_record):
        """
        Enriches company_record in-place.
        Returns True if modified, False if short-circuited or unchanged.
        """
        if not isinstance(company_record, dict):
            return False
        current_domain = str(company_record.get("logo_domain") or "").strip()
        
        # SHORT-CIRCUIT: If a valid logo domain is already found from LinkedIn or DB, skip!
        if current_domain and current_domain.lower() not in BLACKLISTED_DOMAINS:
            return False
            
        website = str(company_record.get("website") or "").strip()
        if website:
            extracted = self._extract_domain(website)
            if extracted and extracted not in BLACKLISTED_DOMAINS:
                comp_name = str(company_record.get("name") or "N/A")
                print(f"[Logo Enricher] Tagged logo domain '{extracted}' from website for '{comp_name}'")
                company_record["logo_domain"] = extracted
                return True
                
        # Fallback: Deduce candidate domain from company name
        name = str(company_record.get("name") or "").strip()
        if name and name != "N/A":
            clean_name = re.sub(r'[^a-zA-Z0-9]', '', name).lower()
            if clean_name:
                candidate = f"{clean_name}.com"
                print(f"[Logo Enricher] Tagged fallback logo domain '{candidate}' for '{name}'")
                company_record["logo_domain"] = candidate
                return True
                
        return False

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
            return domain.split(':')[0] # strip port if any
        except Exception:
            return ""
