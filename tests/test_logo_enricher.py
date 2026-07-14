#!/usr/bin/env python3
"""
Test Suite: tests/test_logo_enricher.py
Verifies SVG logo scraping, resolution, and backend integration.
"""

import unittest
import sys
import os
from unittest.mock import patch, MagicMock

# Add project root to path
workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, workspace_root)
sys.path.insert(0, os.path.join(workspace_root, "data_acquisition"))
sys.path.insert(0, os.path.join(workspace_root, "data_acquisition", "tagging"))

from logo_enricher import LogoEnricher
from backend.services.startup_service import format_startup_summary, format_startup_details, format_lightweight_summary


class TestLogoEnricher(unittest.TestCase):
    def setUp(self):
        self.logo_enricher = LogoEnricher()
        self.patcher = patch("logo_enricher.validate_logo_image", return_value=True)
        self.mock_validate = self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    @patch("requests.get")
    def test_enrich_with_rel_icon_svg(self, mock_get):
        # 1. HTML contains <link rel="icon" type="image/svg+xml" href="/assets/logo.svg">
        html_content = """
        <html>
            <head>
                <link rel="icon" type="image/svg+xml" href="/assets/logo.svg">
            </head>
        </html>
        """
        mock_response = MagicMock(status_code=200, text=html_content)
        mock_get.return_value = mock_response

        company = {"name": "TestCorp", "website": "https://testcorp.com"}
        res = self.logo_enricher.enrich(company)

        self.assertTrue(res)
        self.assertEqual(company["logo_domain"], "testcorp.com")
        self.assertEqual(company["logo_svg_url"], "https://testcorp.com/assets/logo.svg")

    @patch("requests.get")
    def test_enrich_with_shortcut_icon_svg_suffix(self, mock_get):
        # 2. HTML contains <link rel="shortcut icon" href="https://cdn.testcorp.com/favicon.svg?v=2">
        html_content = """
        <html>
            <head>
                <link rel="shortcut icon" href="https://cdn.testcorp.com/favicon.svg?v=2">
            </head>
        </html>
        """
        mock_response = MagicMock(status_code=200, text=html_content)
        mock_get.return_value = mock_response

        company = {"name": "TestCorp", "website": "https://testcorp.com"}
        res = self.logo_enricher.enrich(company)

        self.assertTrue(res)
        self.assertEqual(company["logo_svg_url"], "https://cdn.testcorp.com/favicon.svg?v=2")

    @patch("requests.get")
    def test_enrich_with_any_svg_link_fallback(self, mock_get):
        # 3. HTML contains a generic link tag ending with .svg
        html_content = """
        <html>
            <head>
                <link rel="stylesheet" href="/style.css">
                <link href="img/brand.svg" rel="mask-icon">
            </head>
        </html>
        """
        mock_response = MagicMock(status_code=200, text=html_content)
        mock_get.return_value = mock_response

        company = {"name": "TestCorp", "website": "https://testcorp.com"}
        res = self.logo_enricher.enrich(company)

        self.assertTrue(res)
        self.assertEqual(company["logo_svg_url"], "https://testcorp.com/img/brand.svg")

    @patch("requests.get")
    def test_enrich_fallback_to_root_favicon_svg(self, mock_get):
        # 4. HTML has no SVG links, but server root has /favicon.svg returning 200 SVG
        html_homepage = "<html><head><link rel='shortcut icon' href='/favicon.ico'></head></html>"
        
        mock_home = MagicMock(status_code=200, text=html_homepage)
        mock_favicon = MagicMock(
            status_code=200, 
            headers={"content-type": "image/svg+xml"}, 
            text="<svg xmlns='http://www.w3.org/2000/svg'></svg>"
        )
        
        # requests.get will be called twice for SVG scraping
        mock_get.side_effect = [mock_home, mock_favicon]

        company = {"name": "TestCorp", "website": "https://testcorp.com"}
        res = self.logo_enricher.enrich(company)

        self.assertTrue(res)
        self.assertEqual(company["logo_svg_url"], "https://testcorp.com/favicon.svg")

    @patch("requests.get")
    def test_enrich_handling_non_svg_response_for_fallback(self, mock_get):
        # 5. Homepage has no SVG. /favicon.svg returns 200 html.
        # Then Unavatar returns 404, Google Favicon returns 404.
        html_homepage = "<html></html>"
        mock_home = MagicMock(status_code=200, text=html_homepage)
        mock_favicon = MagicMock(
            status_code=200, 
            headers={"content-type": "text/html"}, 
            text="<html>404 Not Found but 200 OK</html>"
        )
        mock_unavatar = MagicMock(status_code=404)
        mock_google = MagicMock(status_code=404)
        
        mock_get.side_effect = [mock_home, mock_favicon, mock_unavatar, mock_google]

        company = {"name": "TestCorp", "website": "https://testcorp.com"}
        res = self.logo_enricher.enrich(company)

        self.assertTrue(res)
        self.assertEqual(company["logo_svg_url"], "")

    @patch("requests.get")
    def test_enrich_handling_timeout_gracefully(self, mock_get):
        # Request to website times out, and following check APIs also fail/timeout
        mock_get.side_effect = Exception("Connection timed out")

        company = {"name": "TestCorp", "website": "https://testcorp.com"}
        res = self.logo_enricher.enrich(company)

        self.assertTrue(res)
        self.assertEqual(company["logo_svg_url"], "")

    def test_enrich_short_circuits_fully_enriched(self):
        # 7. Already fully enriched startup
        company = {
            "name": "TestCorp",
            "logo_domain": "testcorp.com",
            "logo_svg_url": "https://testcorp.com/logo.svg",
            "website": "https://testcorp.com"
        }
        res = self.logo_enricher.enrich(company)
        self.assertFalse(res)

    @patch("requests.get")
    def test_enrich_does_not_short_circuit_if_empty(self, mock_get):
        # Already has empty logo_svg_url, but we should attempt resolution
        company = {
            "name": "TestCorp",
            "logo_domain": "testcorp.com",
            "logo_svg_url": "",
            "website": "https://testcorp.com"
        }
        # SVG fails, Unavatar succeeds
        html_homepage = "<html></html>"
        mock_home = MagicMock(status_code=200, text=html_homepage)
        mock_favicon = MagicMock(status_code=404)
        mock_unavatar = MagicMock(status_code=200)
        
        mock_get.side_effect = [mock_home, mock_favicon, mock_unavatar]
        
        res = self.logo_enricher.enrich(company)
        self.assertTrue(res)
        self.assertEqual(company["logo_svg_url"], "https://unavatar.io/testcorp.com")

    @patch("requests.get")
    def test_enrich_unavatar_fallback_success(self, mock_get):
        # SVG scraping fails (returns HTML without link, and /favicon.svg returns 404)
        # Unavatar API check returns 200
        html_homepage = "<html></html>"
        mock_home = MagicMock(status_code=200, text=html_homepage)
        mock_favicon = MagicMock(status_code=404)
        mock_unavatar = MagicMock(status_code=200)

        mock_get.side_effect = [mock_home, mock_favicon, mock_unavatar]

        company = {"name": "TestCorp", "website": "https://testcorp.com"}
        res = self.logo_enricher.enrich(company)

        self.assertTrue(res)
        self.assertEqual(company["logo_svg_url"], "https://unavatar.io/testcorp.com")
        # Check that we did not call Google Favicon (mock_get called exactly 3 times)
        self.assertEqual(mock_get.call_count, 3)

    @patch("requests.get")
    def test_enrich_google_favicon_fallback_success(self, mock_get):
        # SVG scraping fails
        # Unavatar returns 404
        # Google Favicon returns 200
        html_homepage = "<html></html>"
        mock_home = MagicMock(status_code=200, text=html_homepage)
        mock_favicon = MagicMock(status_code=404)
        mock_unavatar = MagicMock(status_code=404)
        mock_google = MagicMock(status_code=200)

        mock_get.side_effect = [mock_home, mock_favicon, mock_unavatar, mock_google]

        company = {"name": "TestCorp", "website": "https://testcorp.com"}
        res = self.logo_enricher.enrich(company)

        self.assertTrue(res)
        self.assertEqual(company["logo_svg_url"], "https://www.google.com/s2/favicons?domain=testcorp.com&sz=128")
        self.assertEqual(mock_get.call_count, 4)

    @patch("requests.get")
    def test_enrich_unavatar_rate_limit_fallback_to_google(self, mock_get):
        # SVG scraping fails
        # Unavatar returns 429 (Rate Limit)
        # Google Favicon returns 200
        html_homepage = "<html></html>"
        mock_home = MagicMock(status_code=200, text=html_homepage)
        mock_favicon = MagicMock(status_code=404)
        mock_unavatar = MagicMock(status_code=429)
        mock_google = MagicMock(status_code=200)

        mock_get.side_effect = [mock_home, mock_favicon, mock_unavatar, mock_google]

        company = {"name": "TestCorp", "website": "https://testcorp.com"}
        res = self.logo_enricher.enrich(company)

        self.assertTrue(res)
        self.assertEqual(company["logo_svg_url"], "https://www.google.com/s2/favicons?domain=testcorp.com&sz=128")
        self.assertEqual(mock_get.call_count, 4)

    def test_enrich_skips_when_is_active_website_is_false(self):
        company = {
            "name": "DeadCorp",
            "website": "https://deadcorp.com",
            "logo_svg_url": "https://deadcorp.com/logo.svg",
            "is_active_website": False
        }
        
        # Do not mock requests.get; if it triggers a network request, it will raise an error.
        res = self.logo_enricher.enrich(company)
        
        self.assertTrue(res)
        self.assertEqual(company["logo_svg_url"], "")
        
        # Verify that it returns False if it was already empty
        company_cleared = {
            "name": "DeadCorp",
            "website": "https://deadcorp.com",
            "logo_svg_url": "",
            "is_active_website": False
        }
        res_cleared = self.logo_enricher.enrich(company_cleared)
        self.assertFalse(res_cleared)
        self.assertEqual(company_cleared["logo_svg_url"], "")


class TestBackendStartupLogoUrl(unittest.TestCase):
    def test_format_startup_summary_uses_svg(self):
        startup = {
            "id": 1,
            "name": "TestCorp",
            "logo_domain": "testcorp.com",
            "logo_svg_url": "https://testcorp.com/logo.svg",
            "website": "https://testcorp.com",
            "job_openings": []
        }
        summary = format_startup_summary(startup)
        self.assertEqual(summary["logo_url"], "https://testcorp.com/logo.svg")

    def test_format_startup_summary_empty_logo(self):
        # Formatters serve logo_svg_url directly (which is empty string)
        startup = {
            "id": 2,
            "name": "TestCorp",
            "logo_domain": "testcorp.com",
            "logo_svg_url": "",
            "website": "https://testcorp.com",
            "job_openings": []
        }
        summary = format_startup_summary(startup)
        self.assertEqual(summary["logo_url"], "")

    def test_format_startup_details_uses_svg(self):
        startup = {
            "id": 1,
            "name": "TestCorp",
            "logo_domain": "testcorp.com",
            "logo_svg_url": "https://testcorp.com/logo.svg",
            "website": "https://testcorp.com",
            "job_openings": []
        }
        details = format_startup_details(startup)
        self.assertEqual(details["logo_url"], "https://testcorp.com/logo.svg")

    def test_format_lightweight_summary_uses_svg(self):
        startup = {
            "id": 1,
            "name": "TestCorp",
            "logo_domain": "testcorp.com",
            "logo_svg_url": "https://testcorp.com/logo.svg",
            "website": "https://testcorp.com",
            "job_openings": []
        }
        lightweight = format_lightweight_summary(startup)
        self.assertEqual(lightweight["logo_url"], "https://testcorp.com/logo.svg")


if __name__ == "__main__":
    unittest.main()
