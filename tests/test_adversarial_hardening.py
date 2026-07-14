#!/usr/bin/env python3
"""
Test Suite: tests/test_adversarial_hardening.py
Tier 5: Adversarial Hardening and Zero-Tolerance Database Protection.
"""

import unittest
import sys
import os
import socket
import json
import threading
import tempfile
import shutil
from unittest.mock import patch, MagicMock
import requests

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from data_acquisition.utils.validation import (
    validate_website_domain,
    validate_logo_image,
    check_dns,
    perform_url_check
)
from backend.utils.validators import _sanitize_string
from data_acquisition.db_manager import DBManager


class TestSSRFAndPrivateIPBlocking(unittest.TestCase):
    """Tier 5: Verifies that SSRF attacks using private, loopback, or link-local IPs are blocked."""

    @patch('socket.gethostbyname')
    def test_dns_resolution_private_ranges(self, mock_gethostbyname):
        private_ips = [
            '127.0.0.1', '10.255.255.254', '172.16.0.1', 
            '192.168.1.100', '169.254.169.254', '::1'
        ]
        for ip in private_ips:
            mock_gethostbyname.return_value = ip
            self.assertFalse(check_dns("malicious.local"), f"IP {ip} should be blocked")

    @patch('socket.gethostbyname')
    @patch('requests.head')
    def test_validate_website_domain_blocks_ssrf(self, mock_head, mock_gethostbyname):
        mock_gethostbyname.return_value = '127.0.0.1'
        is_active, _, reason = validate_website_domain('https://localhost-malicious.com')
        self.assertFalse(is_active)
        self.assertEqual(reason, "Private IP range blocked")
        mock_head.assert_not_called()

    @patch('socket.gethostbyname')
    @patch('requests.head')
    def test_validate_logo_image_blocks_ssrf(self, mock_head, mock_gethostbyname):
        mock_gethostbyname.return_value = '169.254.169.254'
        self.assertFalse(validate_logo_image('https://metadata-service.com/logo.png'))
        mock_head.assert_not_called()


class TestRecursiveSanitization(unittest.TestCase):
    """Tier 5: Verifies that sanitizers recursively strip nested HTML/JS tags and filter null bytes."""

    def test_recursive_tag_stripping(self):
        payloads = [
            ("<<script>script>alert(1)</script>", "alert(1)"),
            ("<<img src=x onerror=alert(1)>img src=x onerror=alert(1)>", ""),
            ("Hello <scr<script>ipt>alert(1)</scr</script>ipt> World", "Hello alert(1) World"),
            ("Text with <\x00script>tag and null\x00 byte", "Text with tag and null byte")
        ]
        for inp, expected in payloads:
            self.assertEqual(_sanitize_string(inp), expected)


class TestSVGAndLogoSpoofing(unittest.TestCase):
    """Tier 5: Verifies SVG script injection blocking and MIME/content-type spoofing rejection."""

    @patch('socket.gethostbyname')
    @patch('requests.head')
    @patch('requests.get')
    def test_logo_svg_script_injection_rejected(self, mock_get, mock_head, mock_gethostbyname):
        mock_gethostbyname.return_value = '8.8.8.8'
        
        # HEAD returns ok
        mock_head_res = MagicMock(status_code=200)
        mock_head_res.headers = {"Content-Type": "image/svg+xml"}
        mock_head.return_value = mock_head_res

        # GET returns malicious SVG payload
        mock_get_res = MagicMock(status_code=200)
        mock_get_res.headers = {"Content-Type": "image/svg+xml"}
        mock_get_res.raw.read.return_value = b'<svg><script>alert(1)</script></svg>'
        mock_get_res.__enter__.return_value = mock_get_res
        mock_get.return_value = mock_get_res

        self.assertFalse(validate_logo_image('https://malicious.com/logo.svg'))

    @patch('socket.gethostbyname')
    @patch('requests.head')
    @patch('requests.get')
    def test_logo_spoofed_content_type_rejected(self, mock_get, mock_head, mock_gethostbyname):
        mock_gethostbyname.return_value = '8.8.8.8'
        
        # HEAD claims to be image/png
        mock_head_res = MagicMock(status_code=200)
        mock_head_res.headers = {"Content-Type": "image/png"}
        mock_head.return_value = mock_head_res

        # GET serves SVG script payload spoofed as PNG
        mock_get_res = MagicMock(status_code=200)
        mock_get_res.headers = {"Content-Type": "image/png"}
        mock_get_res.raw.read.return_value = b'<svg onload="alert(1)"></svg>'
        mock_get_res.__enter__.return_value = mock_get_res
        mock_get.return_value = mock_get_res

        self.assertFalse(validate_logo_image('https://malicious.com/spoofed.png'))


class TestFailSafeJSONDatabaseLoading(unittest.TestCase):
    """Tier 5: Verifies that database load failure halts execution rather than destroying DB content."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "startups.json")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_malformed_json_raises_exception(self):
        # Write corrupted/malformed JSON database file
        with open(self.db_path, 'w') as f:
            f.write("{ invalid json [")

        # Initializing or loading database should raise JSONDecodeError
        with self.assertRaises((json.JSONDecodeError, OSError)):
            DBManager(db_path=self.db_path)


class TestDatabaseConcurrencyAndLocks(unittest.TestCase):
    """Tier 5: Verifies read-write advisory lock integrity under heavy thread contention."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "startups.json")
        initial_data = [
            {"id": 1, "name": "Concurrency Corp", "website": "https://concurrency.com", "job_openings": []}
        ]
        with open(self.db_path, 'w') as f:
            json.dump(initial_data, f)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_concurrent_read_write_safety(self):
        db_mgr = DBManager(db_path=self.db_path)
        errors = []

        def worker(thread_id):
            try:
                for i in range(20):
                    # Write/merge new data
                    cand_details = {
                        "name": "Concurrency Corp",
                        "website": f"https://concurrency-{thread_id}-{i}.com",
                        "is_active_website": True
                    }
                    db_mgr.merge_startup(cand_details, [])
                    db_mgr.save_db()
                    
                    # Verify read consistency
                    data = db_mgr.get_all_startups()
                    self.assertTrue(len(data) >= 1)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Encountered concurrency errors: {errors}")


class TestCollisionMetadataHijackingProtection(unittest.TestCase):
    """Tier 5: Verifies that metadata fields cannot be overwritten with blank/malicious duplicate records."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "startups.json")
        
        # Valid seed startup details
        initial_data = [{
            "id": 1,
            "name": "Target Corp",
            "website": "https://target.com",
            "logo_domain": "target.com",
            "logo_svg_url": "https://target.com/logo.png",
            "verified_email": "admin@target.com",
            "description": "Super secure startup.",
            "is_active_website": True,
            "job_openings": []
        }]
        with open(self.db_path, 'w') as f:
            json.dump(initial_data, f)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @patch('data_acquisition.db_manager.validate_logo_image')
    def test_prevent_metadata_overwrite_by_hijacker(self, mock_validate_logo):
        mock_validate_logo.return_value = False  # Candidate logo is invalid
        db_mgr = DBManager(db_path=self.db_path)

        # Merge collision candidate with matching name but unverified/blank details
        hijack_candidate = {
            "name": "Target Corp",
            "website": "N/A",  # Invalid website
            "logo_svg_url": "https://malicious-logo-attacker.com/exploit.png",
            "verified_email": "",
            "description": ""
        }
        
        db_mgr.merge_startup(hijack_candidate, [])
        updated = db_mgr.find_startup("Target Corp", "target.com")
        
        # Original metadata MUST be preserved
        self.assertEqual(updated["website"], "https://target.com")
        self.assertEqual(updated["logo_svg_url"], "https://target.com/logo.png")
        self.assertEqual(updated["verified_email"], "admin@target.com")
        self.assertEqual(updated["description"], "Super secure startup.")


if __name__ == '__main__':
    unittest.main(verbosity=2)
