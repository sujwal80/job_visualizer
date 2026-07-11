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
sys.path.append(workspace_root)
sys.path.append(os.path.join(workspace_root, "data_acquisition"))
sys.path.append(os.path.join(workspace_root, "data_acquisition", "tagging"))

from logo_enricher import LogoEnricher
from backend.services.startup_service import format_startup_summary, format_startup_details, format_lightweight_summary


class TestLogoEnricher(unittest.TestCase):
    def setUp(self):
        self.logo_enricher = LogoEnricher()

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
        
        # requests.get will be called twice: first for homepage, second for /favicon.svg fallback
        mock_get.side_effect = [mock_home, mock_favicon]

        company = {"name": "TestCorp", "website": "https://testcorp.com"}
        res = self.logo_enricher.enrich(company)

        self.assertTrue(res)
        self.assertEqual(company["logo_svg_url"], "https://testcorp.com/favicon.svg")

    @patch("requests.get")
    def test_enrich_handling_non_svg_response_for_fallback(self, mock_get):
        # 5. Homepage has no SVG. /favicon.svg returns a 200 HTML page (trap)
        html_homepage = "<html></html>"
        
        mock_home = MagicMock(status_code=200, text=html_homepage)
        mock_favicon = MagicMock(
            status_code=200, 
            headers={"content-type": "text/html"}, 
            text="<html>404 Not Found but 200 OK</html>"
        )
        
        mock_get.side_effect = [mock_home, mock_favicon]

        company = {"name": "TestCorp", "website": "https://testcorp.com"}
        res = self.logo_enricher.enrich(company)

        self.assertTrue(res)
        self.assertEqual(company["logo_svg_url"], "") # Empty string: scraping attempted and failed

    @patch("requests.get")
    def test_enrich_handling_timeout_gracefully(self, mock_get):
        # 6. Request to homepage times out
        mock_get.side_effect = Exception("Connection timed out")

        company = {"name": "TestCorp", "website": "https://testcorp.com"}
        res = self.logo_enricher.enrich(company)

        self.assertTrue(res)
        self.assertEqual(company["logo_svg_url"], "") # Sets empty string gracefully on error

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


class TestBackendStartupLogoUrl(unittest.TestCase):
    def test_format_startup_summary_uses_svg(self):
        # Startup service using logo_svg_url
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

    def test_format_startup_summary_fallback_to_google_favicon(self):
        # Startup service falling back to Google Favicon API
        startup = {
            "id": 2,
            "name": "TestCorp",
            "logo_domain": "testcorp.com",
            "logo_svg_url": "", # Empty SVG resolved
            "website": "https://testcorp.com",
            "job_openings": []
        }
        summary = format_startup_summary(startup)
        self.assertEqual(summary["logo_url"], "https://www.google.com/s2/favicons?domain=testcorp.com&sz=128")

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
