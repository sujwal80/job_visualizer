#!/usr/bin/env python3
"""
Test Suite: tests/test_industry_classification.py
Verifies the industry classification pipeline, fallback tracks, boundary gates,
and concurrency behavior without touching production data.
"""

import unittest
import sys
import os
import json
import tempfile
import subprocess
import threading
import time
from unittest.mock import patch, MagicMock
import requests

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from data_acquisition.pipelines.tagging.classify_industries import (
    classify_startup,
    run_classification,
    LINKEDIN_MAPPING,
    WIKIDATA_MAPPING
)
from data_acquisition.db_manager import DBManager


class TestIndustryClassification(unittest.TestCase):

    def setUp(self):
        # Set up a generic dummy startup dict
        self.dummy_startup = {
            "id": 1,
            "name": "Test Company",
            "industry": "IT Services and IT Consulting",
            "description": "Providing software development services.",
            "website": "https://testcompany.com",
            "head_count": 50,
            "job_openings": []
        }

    # ==========================================
    # Tier 1 - Feature Coverage (Happy Paths)
    # ==========================================

    def test_direct_linkedin_mapping(self):
        """Tier 1: Mappings in LINKEDIN_MAPPING resolve immediately."""
        # "IT Services and IT Consulting" maps to "Service Industry"
        startup = self.dummy_startup.copy()
        startup["industry"] = "IT Services and IT Consulting"
        result = classify_startup(startup)
        self.assertEqual(result, "Service Industry")

        # "Hospitals and Health Care" maps to "HealthTech"
        startup["industry"] = "Hospitals and Health Care"
        result = classify_startup(startup)
        self.assertEqual(result, "HealthTech")

    @patch('requests.get')
    def test_wikidata_mock_classification(self, mock_get):
        """Tier 1: Correctly validates company type and resolves industry via Wikidata."""
        startup = self.dummy_startup.copy()
        startup["industry"] = "Unknown LinkedIn Industry"
        startup["name"] = "Google"

        # Mock requests.get sequence:
        # 1. Search for entity
        # 2. Get claims
        # 3. Get label of industry
        mock_search_res = MagicMock()
        mock_search_res.status_code = 200
        mock_search_res.json.return_value = {
            "search": [{"id": "Q95"}]
        }

        mock_claims_res = MagicMock()
        mock_claims_res.status_code = 200
        mock_claims_res.json.return_value = {
            "entities": {
                "Q95": {
                    "claims": {
                        "P31": [
                            {"mainsnak": {"datavalue": {"value": {"id": "Q4830453"}}}}  # business enterprise
                        ],
                        "P452": [
                            {"mainsnak": {"datavalue": {"value": {"id": "Q11223"}}}}  # industry id
                        ]
                    }
                }
            }
        }

        mock_label_res = MagicMock()
        mock_label_res.status_code = 200
        mock_label_res.json.return_value = {
            "entities": {
                "Q11223": {
                    "labels": {
                        "en": {"value": "artificial intelligence"}
                    }
                }
            }
        }

        mock_get.side_effect = [mock_search_res, mock_claims_res, mock_label_res]

        # Call classify_startup
        # "artificial intelligence" in WIKIDATA_MAPPING maps to "Artificial Intelligence"
        result = classify_startup(startup)
        self.assertEqual(result, "Artificial Intelligence")
        self.assertEqual(mock_get.call_count, 3)

    def test_taxonomy_keyword_match(self):
        """Tier 1: Text description matches regex pattern in taxonomy."""
        startup = self.dummy_startup.copy()
        startup["industry"] = "Unknown Industry"
        startup["description"] = "We offer a modern marketplace platform and payment services."
        # "marketplace" maps to E-commerce, but "payment" maps to Fintech.
        # Let's test that "Fintech" is matched if it matches first, or just verify a match.
        # Let's check regex patterns:
        # Fintech contains "payment"
        # E-commerce contains "marketplace"
        # Let's use a description that uniquely maps to EdTech.
        startup["description"] = "We offer upskilling courses and online education modules for students."
        result = classify_startup(startup)
        self.assertEqual(result, "EdTech")

    def test_text_normalization_and_ecommerce_keyword_matching(self):
        """Tier 1: Text normalization converts punctuation/multiple spaces and matches e/q-commerce variations."""
        startup = self.dummy_startup.copy()
        startup["industry"] = "Unknown"
        startup["description"] = "We run an e-commerce platform for handmade goods."
        self.assertEqual(classify_startup(startup), "E-commerce")

        # Test e commerce variation with spaces and non-alphanumeric chars
        startup["description"] = "We run an e!@#$commerce platform."
        self.assertEqual(classify_startup(startup), "E-commerce")

        # Test e commerce with multiple spaces
        startup["description"] = "We run an e    commerce platform."
        self.assertEqual(classify_startup(startup), "E-commerce")

        # Test q-commerce variation with hyphen
        startup["description"] = "A next-gen q-commerce company."
        self.assertEqual(classify_startup(startup), "E-commerce")

        # Test q commerce with space
        startup["description"] = "A next-gen q commerce company."
        self.assertEqual(classify_startup(startup), "E-commerce")

    def test_classification_skip_already_set(self):
        """Tier 1: Skips classification if the company has a valid sector."""
        startup = self.dummy_startup.copy()
        # "Fintech" is a valid taxonomy sector
        startup["industry"] = "Fintech"

        with patch('requests.get') as mock_get:
            result = classify_startup(startup, force=False)
            self.assertEqual(result, "Fintech")
            # Should skip Wikidata / LinkedIn / keywords, so requests.get is not called
            mock_get.assert_not_called()

    # ==========================================
    # Tier 2 - Boundary & Corner Cases
    # ==========================================

    def test_headcount_gate_behavior_under_1000(self):
        """Tier 2: Headcount < 1000 includes job titles in keyword search."""
        startup = self.dummy_startup.copy()
        startup["industry"] = "Unknown"
        startup["head_count"] = 999
        # Job title matches EdTech keyword "course"
        startup["job_openings"] = [{"title": "Course Director", "department": "Teaching"}]
        startup["description"] = "Generic text"

        result = classify_startup(startup)
        self.assertEqual(result, "EdTech")

    def test_headcount_gate_behavior_over_equal_1000(self):
        """Tier 2: Headcount >= 1000 excludes job openings from search."""
        startup = self.dummy_startup.copy()
        startup["industry"] = "Unknown"
        startup["head_count"] = 1000
        # Job title matches EdTech keyword "course"
        startup["job_openings"] = [{"title": "Course Director", "department": "Teaching"}]
        startup["description"] = "Generic text"

        # Should fall back to default "SaaS" (or original) because job openings are ignored
        result = classify_startup(startup)
        self.assertEqual(result, "SaaS")

    @patch('requests.get')
    def test_wikidata_invalid_type_rejection(self, mock_get):
        """Tier 2: Non-company QID is rejected and falls back."""
        startup = self.dummy_startup.copy()
        startup["industry"] = "Unknown"
        startup["description"] = "This is a climate and solar power company." # CleanTech

        mock_search_res = MagicMock()
        mock_search_res.status_code = 200
        mock_search_res.json.return_value = {
            "search": [{"id": "Q123"}]
        }

        mock_claims_res = MagicMock()
        mock_claims_res.status_code = 200
        mock_claims_res.json.return_value = {
            "entities": {
                "Q123": {
                    "claims": {
                        "P31": [
                            {"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}  # Human (invalid company QID)
                        ],
                        "P452": [
                            {"mainsnak": {"datavalue": {"value": {"id": "Q11223"}}}}
                        ]
                    }
                }
            }
        }

        mock_get.side_effect = [mock_search_res, mock_claims_res]

        # Should reject Wikidata lookup and fall back to keyword search (CleanTech)
        result = classify_startup(startup)
        self.assertEqual(result, "CleanTech")

    @patch('requests.get')
    def test_wikidata_missing_claims(self, mock_get):
        """Tier 2: Company QID with missing P452 falls back."""
        startup = self.dummy_startup.copy()
        startup["industry"] = "Unknown"
        startup["description"] = "This is a bank and neobank company." # Fintech

        mock_search_res = MagicMock()
        mock_search_res.status_code = 200
        mock_search_res.json.return_value = {
            "search": [{"id": "Q123"}]
        }

        mock_claims_res = MagicMock()
        mock_claims_res.status_code = 200
        mock_claims_res.json.return_value = {
            "entities": {
                "Q123": {
                    "claims": {
                        "P31": [
                            {"mainsnak": {"datavalue": {"value": {"id": "Q4830453"}}}}
                        ]
                        # Missing P452 (industry)
                    }
                }
            }
        }

        mock_get.side_effect = [mock_search_res, mock_claims_res]

        # Should fallback to keywords -> Fintech
        result = classify_startup(startup)
        self.assertEqual(result, "Fintech")

    @patch('requests.get')
    def test_wikidata_timeout_resilience(self, mock_get):
        """Tier 2: Timeout or network exception logs warning and falls back."""
        startup = self.dummy_startup.copy()
        startup["industry"] = "Unknown"
        startup["description"] = "This is a security and identity platform." # Cybersecurity

        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        result = classify_startup(startup)
        # Should catch timeout, return None from wikidata, and fallback to keywords -> Cybersecurity
        self.assertEqual(result, "Cybersecurity")

    def test_force_flag_reclassification(self):
        """Tier 2: force=True overwrites existing valid sectors."""
        startup = self.dummy_startup.copy()
        startup["industry"] = "Fintech" # Valid sector
        startup["description"] = "We do medical healthcare research." # HealthTech

        # force=False should keep Fintech
        result = classify_startup(startup, force=False)
        self.assertEqual(result, "Fintech")

        # force=True should re-classify via keywords -> HealthTech
        result = classify_startup(startup, force=True)
        self.assertEqual(result, "HealthTech")

    # ==========================================
    # Tier 3 - Cross-Feature Combinations
    # ==========================================

    @patch('requests.get')
    def test_wikidata_unmapped_label_fallback(self, mock_get):
        """Tier 3: Wikidata industry label is unmapped, falls back to keywords."""
        startup = self.dummy_startup.copy()
        startup["industry"] = "Unknown"
        startup["description"] = "This company offers a retail shopping app." # E-commerce

        mock_search_res = MagicMock()
        mock_search_res.status_code = 200
        mock_search_res.json.return_value = {
            "search": [{"id": "Q99"}]
        }

        mock_claims_res = MagicMock()
        mock_claims_res.status_code = 200
        mock_claims_res.json.return_value = {
            "entities": {
                "Q99": {
                    "claims": {
                        "P31": [
                            {"mainsnak": {"datavalue": {"value": {"id": "Q4830453"}}}}
                        ],
                        "P452": [
                            {"mainsnak": {"datavalue": {"value": {"id": "Q999"}}}}
                        ]
                    }
                }
            }
        }

        mock_label_res = MagicMock()
        mock_label_res.status_code = 200
        mock_label_res.json.return_value = {
            "entities": {
                "Q999": {
                    "labels": {
                        "en": {"value": "some random unmapped industry label"}
                    }
                }
            }
        }

        mock_get.side_effect = [mock_search_res, mock_claims_res, mock_label_res]

        # Wikidata returns unmapped label -> falls back to keywords -> E-commerce
        result = classify_startup(startup)
        self.assertEqual(result, "E-commerce")

    @patch('requests.get')
    def test_priority_conflict_resolution(self, mock_get):
        """Tier 3: LinkedIn mapping takes priority over Wikidata."""
        startup = self.dummy_startup.copy()
        startup["industry"] = "IT Services and IT Consulting" # maps to Service Industry
        startup["name"] = "ConflictCompany"

        # If Wikidata were queried, it might return QID mapping to Fintech.
        # But since LinkedIn maps directly, Wikidata should not even be called.
        result = classify_startup(startup)
        self.assertEqual(result, "Service Industry")
        mock_get.assert_not_called()

    def test_concurrent_db_locking(self):
        """Tier 3: Verifies DBManager.file_lock prevents concurrent write corruption."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = os.path.join(tmpdir, "startups_test_lock.json")
            
            # Write initial empty array
            with open(temp_db, "w") as f:
                json.dump([], f)

            db = DBManager(db_path=temp_db)

            # We will spawn multiple threads writing in parallel to check if the file lock prevents corruption
            errors = []
            def writer_thread(thread_id):
                try:
                    for i in range(10):
                        with DBManager.file_lock(temp_db):
                            db.load_db()
                            # Append a new startup
                            startups = db.get_all_startups()
                            startups.append({
                                "id": f"t{thread_id}-{i}",
                                "name": f"Company {thread_id}-{i}",
                                "industry": "SaaS"
                            })
                            db.save_db()
                        time.sleep(0.01)
                except Exception as e:
                    errors.append(e)

            threads = []
            for t_id in range(5):
                t = threading.Thread(target=writer_thread, args=(t_id,))
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            self.assertEqual(len(errors), 0, f"Encountered concurrent writing errors: {errors}")

            # Verify that we ended up with exactly 50 startups
            db.load_db()
            self.assertEqual(len(db.get_all_startups()), 50)

    # ==========================================
    # Tier 4 - Real-World Scenarios
    # ==========================================

    def test_cli_classification_database_updates(self):
        """Tier 4: subprocess run of classify_industries.py correctly updates temp database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = os.path.join(tmpdir, "startups_cli_test.json")

            # Create test startups
            test_data = [
                {
                    "id": 1,
                    "name": "QuickPay",
                    "industry": "Banking", # maps to Fintech via LinkedIn
                    "description": "We process payments.",
                    "website": "https://quickpay.com",
                    "head_count": 10
                },
                {
                    "id": 2,
                    "name": "CustomIT",
                    "industry": "Unknown",
                    "description": "We offer custom it services.", # maps to Service Industry via keywords
                    "website": "https://customit.com",
                    "head_count": 20
                }
            ]

            with open(temp_db, "w") as f:
                json.dump(test_data, f, indent=2)

            script_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "data_acquisition", "pipelines", "tagging", "classify_industries.py")
            )

            # Run classify_industries.py as a subprocess on the temp db
            cmd = [sys.executable, script_path, "--db-path", temp_db]
            
            # Mock requests.get inside the subprocess might call Wikidata.
            # Wait, if the subprocess runs, it executes a real HTTP request to Wikidata or times out!
            # Since we must air-gap it, we want Wikidata lookup to be skipped or fail, and fall back to keywords.
            # To prevent the subprocess from making real network calls (or hanging on them),
            # we can pass a dummy environment or the mock Wikidata requests.get inside the script?
            # Wait, we can't easily mock requests inside a standard python subprocess unless we mock the whole requests module.
            # But wait: if QuickPay maps via LinkedIn directly, and CustomIT maps via keywords,
            # does the script even need to query Wikidata?
            # For QuickPay: industry is "Banking" -> maps to Fintech via LINKEDIN_MAPPING. No Wikidata query.
            # For CustomIT: industry is "Unknown" -> no LinkedIn mapping. Script tries Wikidata for "CustomIT".
            # If CustomIT is queried on Wikidata, it might fail or time out (or succeed if it is a real company, but we are in CODE_ONLY mode so it must fail/timeout since there is no network).
            # Wait! In CODE_ONLY network mode, there is no internet access. So any real requests.get in the subprocess will fail immediately (DNS resolution error or connection error).
            # The script has `try ... except Exception as e` which catches the error, logs a warning, and falls back to keyword matching.
            # For CustomIT, the keyword search will match "it services" and assign "Service Industry".
            env = {**os.environ, "DISABLE_WIKIDATA": "1"}
            res = subprocess.run(cmd, capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, 0, f"CLI exited with error: {res.stderr}\nStdout: {res.stdout}")

            # Load the database and check classifications
            with open(temp_db, "r") as f:
                updated_data = json.load(f)

            # QuickPay should be updated to "Fintech"
            self.assertEqual(updated_data[0]["industry"], "Fintech")

            # CustomIT should be updated to "Service Industry"
            self.assertEqual(updated_data[1]["industry"], "Service Industry")


if __name__ == '__main__':
    unittest.main(verbosity=2)
