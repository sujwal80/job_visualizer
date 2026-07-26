import os
import sys
import unittest
from unittest.mock import patch, MagicMock

workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)

from data_acquisition.pipelines.crawling.job_scrapers.yc_scraper import YCScraper
from data_acquisition.pipelines.crawling.job_scrapers.naukri_scraper import NaukriScraper
from data_acquisition.db_manager import DBManager
from data_acquisition.pipelines.validation.job_validator import JobValidator
from data_acquisition.pipelines.crawling.job_scrapers.job_metadata_extractor import extract_job_metadata
from data_acquisition.pipelines.tagging.logo_enricher import LogoEnricher
from data_acquisition.utils.validation import validate_logo_image, is_blacklisted_domain


class TestDataAcquisitionPipeline(unittest.TestCase):

    def setUp(self):
        self.patch_val_web = patch(
            "data_acquisition.db_manager.validate_website_domain",
            side_effect=lambda url, *args, **kwargs: (True, url, None)
        )
        self.patch_val_web_validator = patch(
            "data_acquisition.pipelines.validation.job_validator.validate_website_domain",
            side_effect=lambda url, *args, **kwargs: (True, url, None)
        )
        self.patch_check_job = patch(
            "data_acquisition.db_manager.check_job_active",
            return_value=(True, "Active")
        )
        self.mock_val_web = self.patch_val_web.start()
        self.mock_val_web_validator = self.patch_val_web_validator.start()
        self.mock_check_job = self.patch_check_job.start()

    def tearDown(self):
        self.patch_val_web.stop()
        self.patch_val_web_validator.stop()
        self.patch_check_job.stop()

    def test_clean_environment_variable_loading_defaults(self):
        """
        Verify that default values are loaded cleanly when environment variables are unset.
        """
        with patch.dict(os.environ, {}, clear=True):
            yc = YCScraper()
            self.assertEqual(yc.app_id, "45BWZJ1SGC")
            self.assertTrue(len(yc.api_key) > 0)

            naukri = NaukriScraper()
            self.assertEqual(naukri.headers.get("appid"), "109")
            self.assertEqual(naukri.headers.get("systemid"), "109")

            db = DBManager()
            self.assertEqual(db.db_path, "backend/startups.json")

    def test_environment_variable_configuration_overrides(self):
        """
        Verify that environment variables cleanly override default credentials and configuration paths.
        """
        custom_env = {
            "YC_ALGOLIA_APP_ID": "CUSTOM_YC_APP",
            "YC_ALGOLIA_API_KEY": "CUSTOM_YC_KEY",
            "YC_USER_AGENT": "TestYCUserAgent/1.0",
            "NAUKRI_APP_ID": "999",
            "NAUKRI_SYSTEM_ID": "888",
            "NAUKRI_USER_AGENT": "TestNaukriAgent/1.0",
            "STARTUP_DB_PATH": os.path.join(workspace_root, "tmp/custom/test/path/startups.json")
        }
        with patch.dict(os.environ, custom_env, clear=True):
            yc = YCScraper()
            self.assertEqual(yc.app_id, "CUSTOM_YC_APP")
            self.assertEqual(yc.api_key, "CUSTOM_YC_KEY")
            self.assertEqual(yc.headers["User-Agent"], "TestYCUserAgent/1.0")

            naukri = NaukriScraper()
            self.assertEqual(naukri.headers["appid"], "999")
            self.assertEqual(naukri.headers["systemid"], "888")
            self.assertEqual(naukri.headers["User-Agent"], "TestNaukriAgent/1.0")

            db = DBManager()
            self.assertEqual(db.db_path, os.path.join(workspace_root, "tmp/custom/test/path/startups.json"))

    def test_functional_pipeline_schema_normalization(self):
        """
        Verify schema normalization (url vs job_url) across db_manager and job_validator.
        """
        db = DBManager("/tmp/test_pipeline_schema_norm.json")
        db.startups = []

        company_details = {
            "name": "NormalizationCorp",
            "website": "https://normalizationcorp.io"
        }
        jobs = [
            {"title": "Backend Engineer", "url": "https://normalizationcorp.io/job/backend"},
            {"title": "Frontend Engineer", "job_url": "https://normalizationcorp.io/job/frontend"},
            {"title": "DevOps Engineer", "url": "https://normalizationcorp.io/job/devops", "job_url": "https://normalizationcorp.io/job/devops"}
        ]

        with patch.object(db, "geocode_address", return_value=(12.9716, 77.5946)):
            db.merge_startup(company_details, jobs, target_city="Bengaluru")

        self.assertEqual(len(db.startups), 1)
        startup = db.startups[0]
        self.assertEqual(len(startup["job_openings"]), 3)

        for job in startup["job_openings"]:
            self.assertIn("url", job)
            self.assertIn("job_url", job)
            self.assertTrue(job["url"].startswith("https://normalizationcorp.io/job/"))
            self.assertEqual(job["url"], job["job_url"])

        # Test JobValidator preserving normalization
        validator = JobValidator(db)
        with patch.object(validator, "_check_job_active", return_value=(True, "Active")):
            validator.validate_and_prune()

        for job in db.startups[0]["job_openings"]:
            self.assertEqual(job["url"], job["job_url"])

    def test_resilience_against_malformed_payloads(self):
        """
        Verify that data acquisition components handle malformed job payloads, non-dict records,
        and missing fields without raising unhandled exceptions.
        """
        db = DBManager("/tmp/test_resilience.json")
        db.startups = []

        # Pass malformed company and job inputs
        with patch.object(db, "geocode_address", return_value=(None, None)):
            db.merge_startup("not_a_dict", [{"title": "Good Job", "url": "http://good.io"}])
            self.assertEqual(len(db.startups), 0)

            malformed_jobs = [
                None,
                12345,
                "not_a_job_dict",
                {"url": "https://example.com/no-title"},
                {"title": None, "url": None},
                {"title": "Valid Role", "url": "https://example.com/valid"}
            ]
            db.merge_startup({"name": "ResilientCorp"}, malformed_jobs)

        self.assertEqual(len(db.startups), 1)
        valid_jobs_saved = db.startups[0]["job_openings"]
        self.assertEqual(len(valid_jobs_saved), 1)
        self.assertEqual(valid_jobs_saved[0]["title"], "Valid Role")
        self.assertEqual(valid_jobs_saved[0]["url"], "https://example.com/valid")
        self.assertEqual(valid_jobs_saved[0]["job_url"], "https://example.com/valid")

        # Test JobValidator resilience with malformed existing job_openings
        db.startups[0]["job_openings"].extend([None, 999, {"url": "N/A", "title": "Bad URL Role"}])
        validator = JobValidator(db)
        with patch.object(validator, "_check_job_active", return_value=(True, "Active")):
            validator.validate_and_prune()
        self.assertEqual(len(db.startups[0]["job_openings"]), 1)

        # Test extract_job_metadata resilience against non-string inputs
        meta1 = extract_job_metadata(None, None, None)
        self.assertIsInstance(meta1, dict)
        self.assertEqual(meta1["experience"], "Not specified")

        meta2 = extract_job_metadata(12345, 67890, extra_data={"skills": [None, 123, "Python"]})
        self.assertIsInstance(meta2, dict)
        self.assertIn("Python", meta2["skills"])

    def test_logo_enricher_no_fake_com_domain_synthesis(self):
        """Verify LogoEnricher no longer constructs fake .com domains when logo_domain is missing."""
        enricher = LogoEnricher()
        startup = {"name": "NoDomainStartup", "website": "", "logo_domain": "", "logo_svg_url": ""}
        enricher.enrich(startup)
        self.assertEqual(startup.get("logo_domain"), "")
        self.assertEqual(startup.get("logo_svg_url"), "")

    def test_validate_logo_image_rejects_favicons_pixels_and_fallbacks(self):
        """Verify validate_logo_image rejects default 16x16 Google icons, 1x1 transparent pixels, and Unavatar 404 fallbacks."""
        # 16x16 Google favicon URL
        self.assertFalse(validate_logo_image("https://www.google.com/s2/favicons?domain=example.com&sz=128"))

        # 1x1 PNG pixel bytes
        png_1x1 = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
        )
        self.assertFalse(validate_logo_image("https://example.com/pixel.png", content_bytes=png_1x1))

        # 16x16 PNG icon bytes
        png_16x16 = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10'
            b'\x00\x00\x00\x10\x08\x06\x00\x00\x00\xff\xff\xff'
        )
        self.assertFalse(validate_logo_image("https://example.com/favicon.png", content_bytes=png_16x16))

        # Unavatar fallback header
        unavatar_headers = {"x-unavatar-fallback": "true", "Content-Type": "image/png"}
        self.assertFalse(validate_logo_image("https://unavatar.io/example.com", content_bytes=b"dummy_bytes", headers=unavatar_headers))

    def test_candidate_websites_shortener_or_aggregator_rejected(self):
        """Verify candidate company websites that are shortener or aggregator URLs (goo.gle, linkedin.com) are rejected and set to ""."""
        self.assertTrue(is_blacklisted_domain("goo.gle"))
        self.assertTrue(is_blacklisted_domain("careers.linkedin.com"))
        self.assertTrue(is_blacklisted_domain("start.myjar.app"))
        self.assertTrue(is_blacklisted_domain("bit.ly"))

        db = DBManager(":memory:")
        clean_url1, dom1 = db._clean_url_and_domain("https://goo.gle/shortener")
        self.assertEqual(dom1, "")
        clean_url2, dom2 = db._clean_url_and_domain("https://careers.linkedin.com/jobs")
        self.assertEqual(dom2, "")

    def test_find_startup_canonical_matching_jar_variants(self):
        """Verify DBManager.find_startup matches Jar, Jar Pvt Ltd, and Jar Technologies to canonical record."""
        db = DBManager(":memory:")
        db.startups = [
            {
                "id": 1,
                "name": "Jar",
                "city": "Bengaluru",
                "website": "https://myjar.app",
                "logo_domain": "myjar.app",
                "job_openings": []
            }
        ]
        match_jar = db.find_startup("Jar", "")
        self.assertIsNotNone(match_jar)
        self.assertEqual(match_jar["id"], 1)

        match_pvt = db.find_startup("Jar Pvt Ltd", "")
        self.assertIsNotNone(match_pvt)
        self.assertEqual(match_pvt["id"], 1)

        match_tech = db.find_startup("Jar Technologies", "")
        self.assertIsNotNone(match_tech)
        self.assertEqual(match_tech["id"], 1)

    def test_merge_job_openings_rejects_cross_company_slug_mismatch(self):
        """Verify DBManager._merge_job_openings rejects job URLs whose slugs name a different company than target record."""
        db = DBManager(":memory:")
        startup = {"id": 1, "name": "Namma Cart", "job_openings": []}

        mismatched_job = {
            "title": "Software Engineer",
            "url": "https://www.naukri.com/job-listings-software-engineer-at-flipkart-bangalore-4417583838",
            "company_name": "Flipkart"
        }
        valid_job = {
            "title": "Backend Developer",
            "url": "https://www.naukri.com/job-listings-backend-developer-at-namma-cart-bangalore-12345",
            "company_name": "Namma Cart"
        }

        with patch("data_acquisition.db_manager.check_job_active", return_value=(True, "Active")):
            db._merge_job_openings(startup, [mismatched_job, valid_job])

        openings = startup.get("job_openings", [])
        self.assertEqual(len(openings), 1)
        self.assertEqual(openings[0]["title"], "Backend Developer")

    def test_production_dataset_cleanup_zero_inconsistencies(self):
        """Verify production dataset cleanup leaves 0 duplicate company groups, 0 fake/blacklisted domains, 0 invalid logos, and 0 mismatched jobs in backend/startups.json."""
        prod_db_path = os.path.join(workspace_root, "backend/startups.json")
        self.assertTrue(os.path.exists(prod_db_path))

        db = DBManager(prod_db_path)
        startups = db.startups
        self.assertGreater(len(startups), 0)

        # 1. Check zero duplicate company groups
        group_keys = set()
        for s in startups:
            name = str(s.get("name") or "").strip()
            base_norm = db._normalize_base_text(name)
            key = base_norm if base_norm else db._normalize_text(name)
            self.assertNotIn(key, group_keys, f"Duplicate company group key found in prod db: '{key}' ({name})")
            group_keys.add(key)
            self.assertFalse(db.is_aggregator_name(name), f"Aggregator startup name found in prod db: '{name}'")

        # 2. Check zero fake/blacklisted domains
        for s in startups:
            web = str(s.get("website") or "").strip()
            if web:
                self.assertFalse(is_blacklisted_domain(web), f"Blacklisted website found: '{web}' in startup '{s.get('name')}'")
            logo_dom = str(s.get("logo_domain") or "").strip()
            if logo_dom:
                self.assertFalse(is_blacklisted_domain(logo_dom), f"Blacklisted logo domain found: '{logo_dom}' in startup '{s.get('name')}'")

        # 3. Check zero invalid logos
        for s in startups:
            logo = str(s.get("logo_svg_url") or "").strip()
            if logo:
                self.assertNotIn("google.com/s2/favicons", logo, f"Google favicon URL found in prod db logo: '{logo}'")
                self.assertFalse(is_blacklisted_domain(logo), f"Blacklisted logo URL found: '{logo}'")

        # 4. Check zero mismatched jobs
        for s in startups:
            sname = s.get("name", "")
            for j in s.get("job_openings", []):
                self.assertIsInstance(j, dict)
                comp_name = j.get("company_name") or j.get("company")
                self.assertFalse(db.is_aggregator_name(comp_name), f"Aggregator job company name found: '{comp_name}' under '{sname}'")
                self.assertFalse(db._is_job_slug_mismatched(j, sname), f"Mismatched job slug found: '{j.get('url')}' under '{sname}'")


if __name__ == '__main__':
    unittest.main()

