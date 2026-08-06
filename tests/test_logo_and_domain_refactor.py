import unittest
from unittest.mock import MagicMock, patch
import os

from data_acquisition.utils.validation import is_blacklisted_domain, validate_logo_image, get_image_dimensions
from data_acquisition.pipelines.tagging.logo_enricher import LogoEnricher
from data_acquisition.db_manager import DBManager
from data_acquisition.enrich_all_official_logos import get_logo_candidate_score, extract_linkedin_slug

class TestLogoAndDomainRefactor(unittest.TestCase):

    def test_is_blacklisted_domain_exact_and_subdomain(self):
        """Test domain blacklisting for exact domains and subdomains."""
        # Exact blacklisted domains
        self.assertTrue(is_blacklisted_domain("linkedin.com"))
        self.assertTrue(is_blacklisted_domain("myjar.app"))
        self.assertTrue(is_blacklisted_domain("goo.gle"))
        self.assertTrue(is_blacklisted_domain("cutshort.io"))
        self.assertTrue(is_blacklisted_domain("naukri.com"))
        self.assertTrue(is_blacklisted_domain("wellfound.com"))
        self.assertTrue(is_blacklisted_domain("glassdoor.com"))
        self.assertTrue(is_blacklisted_domain("indeed.com"))
        self.assertTrue(is_blacklisted_domain("hirist.com"))
        self.assertTrue(is_blacklisted_domain("hirist.tech"))
        self.assertTrue(is_blacklisted_domain("ycombinator.com"))
        self.assertTrue(is_blacklisted_domain("internshala.com"))

        # Subdomains
        self.assertTrue(is_blacklisted_domain("careers.linkedin.com"))
        self.assertTrue(is_blacklisted_domain("start.myjar.app"))
        self.assertTrue(is_blacklisted_domain("jobs.naukri.com"))
        self.assertTrue(is_blacklisted_domain("sub.bit.ly"))
        self.assertTrue(is_blacklisted_domain("www.glassdoor.com"))

        # Non-blacklisted domains
        self.assertFalse(is_blacklisted_domain("realstartup.io"))
        self.assertFalse(is_blacklisted_domain("mycompany.com"))
        self.assertFalse(is_blacklisted_domain("acme.org"))
        self.assertFalse(is_blacklisted_domain(""))
        self.assertFalse(is_blacklisted_domain(None))

    def test_logo_enricher_eliminates_fake_domain_synthesis(self):
        """Test that LogoEnricher does NOT synthesize fake .com domains from company name."""
        enricher = LogoEnricher()
        company = {
            "name": "Acme Innovations",
            "website": "",
            "logo_domain": "",
            "logo_svg_url": ""
        }
        modified = enricher.enrich(company)
        # Should not create acmeinnovations.com
        self.assertEqual(company.get("logo_domain"), "")
        self.assertEqual(company.get("logo_svg_url"), "")

    def test_logo_enricher_clears_blacklisted_domain(self):
        """Test that LogoEnricher clears blacklisted domains and subdomains."""
        enricher = LogoEnricher()
        company = {
            "name": "Tech Corp",
            "website": "https://careers.linkedin.com/jobs",
            "logo_domain": "careers.linkedin.com",
            "logo_svg_url": ""
        }
        enricher.enrich(company)
        self.assertEqual(company.get("logo_domain"), "")

    def test_get_image_dimensions_png_gif_jpeg(self):
        """Test binary header parsing for image dimensions."""
        # 1x1 transparent PNG bytes
        png_1x1 = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
        )
        w, h = get_image_dimensions(png_1x1)
        self.assertEqual((w, h), (1, 1))

        # 16x16 PNG bytes
        png_16x16 = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10'
            b'\x00\x00\x00\x10\x08\x06\x00\x00\x00\xff\xff\xff'
        )
        w, h = get_image_dimensions(png_16x16)
        self.assertEqual((w, h), (16, 16))

    def test_validate_logo_image_rejects_1x1_and_16x16(self):
        """Test validate_logo_image rejects 1x1 and 16x16 icons."""
        png_1x1 = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
        )
        png_16x16 = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10'
            b'\x00\x00\x00\x10\x08\x06\x00\x00\x00\xff\xff\xff'
        )
        self.assertFalse(validate_logo_image("https://startup.com/pixel.png", content_bytes=png_1x1))
        self.assertFalse(validate_logo_image("https://startup.com/favicon.png", content_bytes=png_16x16))

    def test_validate_logo_image_rejects_unavatar_fallback_header(self):
        """Test validate_logo_image rejects Unavatar fallback responses via header."""
        valid_bytes = b"some_image_data_here"
        headers = {"x-unavatar-fallback": "true", "Content-Type": "image/png"}
        self.assertFalse(validate_logo_image("https://unavatar.io/mydomain.com", content_bytes=valid_bytes, headers=headers))

    def test_validate_logo_image_rejects_blacklisted_domain_logos(self):
        """Test validate_logo_image rejects logos from blacklisted domains."""
        self.assertFalse(validate_logo_image("https://linkedin.com/logo.png"))
        self.assertFalse(validate_logo_image("https://careers.linkedin.com/logo.png"))
        self.assertFalse(validate_logo_image("https://start.myjar.app/logo.png"))

    def test_db_manager_clean_url_and_domain_subdomain_blacklist(self):
        """Test DBManager._clean_url_and_domain rejects blacklisted subdomains."""
        db = DBManager(db_path=":memory:")
        clean_url, domain = db._clean_url_and_domain("https://careers.linkedin.com/jobs/123")
        self.assertEqual(domain, "")

        clean_url, domain = db._clean_url_and_domain("https://start.myjar.app/home")
        self.assertEqual(domain, "")

        clean_url, domain = db._clean_url_and_domain("https://mycompany.com/about")
        self.assertEqual(domain, "mycompany.com")

    def test_get_logo_candidate_score_prioritizes_high_res(self):
        """Test logo quality scoring hierarchy."""
        # SVGs should outscore PNGs and favicons
        svg_score = get_logo_candidate_score("https://mycompany.com/logo.svg", "svg_logo")
        ln_score = get_logo_candidate_score("https://media.licdn.com/dms/image/v2/C560BAQHG/company-logo_200_200/0/1638200?e=1710", "linkedin_logo")
        apple_score = get_logo_candidate_score("https://mycompany.com/apple-touch-icon.png", "apple_touch_icon")
        google_score = get_logo_candidate_score("https://www.google.com/s2/favicons?domain=mycompany.com", "google_favicon")

        self.assertGreater(svg_score, ln_score)
        self.assertGreater(ln_score, apple_score)
        self.assertGreater(apple_score, google_score)

        # Junk banners should be scored as 0
        banner_score = get_logo_candidate_score("https://mycompany.com/hero-banner-logo.png", "brand_img")
        self.assertEqual(banner_score, 0)

    def test_extract_linkedin_slug_from_jobs(self):
        """Test extracting linkedin company slug from startup jobs or fields."""
        startup_with_job = {
            "name": "Acme Corp",
            "job_openings": [
                {"title": "SDE-1", "company_slug": "acme-corp-technologies"}
            ]
        }
        self.assertEqual(extract_linkedin_slug(startup_with_job), "acme-corp-technologies")

if __name__ == "__main__":
    unittest.main()
