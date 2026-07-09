import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure workspace root and data_acquisition are in sys.path
workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
data_acq_dir = os.path.join(workspace_root, 'data_acquisition')
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)
if data_acq_dir not in sys.path:
    sys.path.insert(0, data_acq_dir)

from yc_scraper import YCScraper
from naukri_scraper import NaukriScraper
from db_manager import DBManager
from job_validator import JobValidator
from job_metadata_extractor import extract_job_metadata


class TestDataAcquisitionPipeline(unittest.TestCase):

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
            "STARTUP_DB_PATH": "/custom/test/path/startups.json"
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
            self.assertEqual(db.db_path, "/custom/test/path/startups.json")

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


if __name__ == '__main__':
    unittest.main()
