#!/usr/bin/env python3
import unittest
import sys
import os
import socket
import requests
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class TestScraperBaseIntegratedValidation(unittest.TestCase):
    """Verifies ScraperBase integrates metadata extraction and job validation."""

    def test_validate_and_enrich_jobs_filters_inactive(self):
        from data_acquisition.pipelines.crawling.job_scrapers.scraper_base import ScraperBase
        from unittest.mock import MagicMock
        
        mock_validator = MagicMock()
        # First job returns active, second returns inactive
        mock_validator._check_job_active.side_effect = [
            (True, "Active"),
            (False, "Expired role")
        ]
        
        base = ScraperBase(validator=mock_validator)
        raw_jobs = [
            {"title": "Senior Python Engineer", "url": "https://example.com/job/1", "description": "Need 4 years experience in Python and AWS."},
            {"title": "Closed Role", "url": "https://example.com/job/2", "description": "Expired"}
        ]
        res = base.validate_and_enrich_jobs(raw_jobs)
        self.assertEqual(len(res), 1, "Only active jobs should be returned by ScraperBase")
        self.assertEqual(res[0]["title"], "Senior Python Engineer")
        self.assertIn("Python", res[0]["skills"])
        self.assertIn("AWS", res[0]["skills"])


class TestValidationUtils(unittest.TestCase):
    """Unit tests for check_dns and validate_website_domain with mock patches."""

    @patch('socket.gethostbyname')
    def test_check_dns_success(self, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.3.4'
        from data_acquisition.utils.validation import check_dns
        self.assertTrue(check_dns('example.com'))
        mock_gethostbyname.assert_called_once_with('example.com')

    @patch('socket.gethostbyname')
    def test_check_dns_failure(self, mock_gethostbyname):
        mock_gethostbyname.side_effect = socket.gaierror('mock gaierror')
        from data_acquisition.utils.validation import check_dns
        self.assertFalse(check_dns('invalid-domain.com'))
        mock_gethostbyname.assert_called_once_with('invalid-domain.com')

    @patch('socket.gethostbyname')
    @patch('requests.get')
    @patch('requests.head')
    def test_validate_website_domain_success(self, mock_head, mock_get, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.3.4'
        
        # Mock requests.head success
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.url = 'https://rupeek.com'
        mock_head.return_value = mock_res

        # Mock requests.get for parking page check
        mock_get_res = MagicMock()
        mock_get_res.status_code = 200
        mock_get_res.url = 'https://rupeek.com'
        mock_get_res.text = "Some non-parking HTML content with <body> tag."
        mock_get_res.content = b"Some non-parking HTML content with <body> tag."
        mock_get_res.headers = {}
        mock_get.return_value = mock_get_res

        from data_acquisition.utils.validation import validate_website_domain
        is_active, healed_url, reason = validate_website_domain('https://rupeek.com')
        self.assertTrue(is_active)
        self.assertEqual(healed_url, 'https://rupeek.com')
        self.assertIsNone(reason)
        mock_head.assert_called_once()
        mock_get.assert_called_once()


    @patch('socket.gethostbyname')
    @patch('requests.get')
    @patch('requests.head')
    def test_validate_website_domain_self_healing(self, mock_head, mock_get, mock_gethostbyname):
        # We start with https://www.rupeek.com
        # Primary domain is www.rupeek.com, alt_domain is rupeek.com
        # Mock DNS: www.rupeek.com fails, rupeek.com succeeds
        def dns_side_effect(domain):
            if domain == 'www.rupeek.com':
                raise socket.gaierror('Mock DNS fail')
            return '1.2.3.4'
        mock_gethostbyname.side_effect = dns_side_effect

        # Mock requests for rupeek.com to succeed
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.url = 'https://rupeek.com'
        mock_head.return_value = mock_res

        from data_acquisition.utils.validation import validate_website_domain
        is_active, healed_url, reason = validate_website_domain('https://www.rupeek.com')
        self.assertTrue(is_active)
        self.assertEqual(healed_url, 'https://rupeek.com')
        self.assertIsNone(reason)

    @patch('socket.gethostbyname')
    @patch('requests.get')
    @patch('requests.head')
    def test_validate_website_domain_failure(self, mock_head, mock_get, mock_gethostbyname):
        # kora.ai DNS fails, www.kora.ai DNS fails, and fallback direct request fails
        mock_gethostbyname.side_effect = socket.gaierror('Mock DNS fail')
        
        mock_head.side_effect = requests.exceptions.ConnectionError('Mock connection fail')
        mock_get.side_effect = requests.exceptions.ConnectionError('Mock connection fail')

        from data_acquisition.utils.validation import validate_website_domain
        is_active, healed_url, reason = validate_website_domain('https://kora.ai')
        self.assertFalse(is_active)
        self.assertEqual(healed_url, 'https://kora.ai')
        self.assertIn('Mock connection fail', reason)

    @patch('socket.gethostbyname')
    @patch('requests.get')
    @patch('requests.head')
    def test_validate_website_domain_ssl_fallback_success(self, mock_head, mock_get, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.3.4'
        
        # First call to requests.head with https:// throws SSLError
        # Second call to requests.head with http:// succeeds
        mock_head.side_effect = [
            requests.exceptions.SSLError("HTTPS SSL Error"),
            MagicMock(status_code=200, url="http://rupeek.com", headers={})
        ]
        
        # Mock requests.get for parking page check (which runs on http://rupeek.com)
        mock_get_res = MagicMock()
        mock_get_res.status_code = 200
        mock_get_res.url = 'http://rupeek.com'
        mock_get_res.text = "Some normal site text"
        mock_get_res.content = b"Some normal site text"
        mock_get_res.headers = {}
        mock_get.return_value = mock_get_res

        from data_acquisition.utils.validation import validate_website_domain
        is_active, healed_url, reason = validate_website_domain('https://rupeek.com')
        self.assertTrue(is_active)
        self.assertEqual(healed_url, 'http://rupeek.com')
        self.assertIsNone(reason)

    @patch('socket.gethostbyname')
    @patch('requests.get')
    @patch('requests.head')
    def test_validate_website_domain_ssl_fallback_failure(self, mock_head, mock_get, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.3.4'
        
        # HTTPS throws SSLError, HTTP fallback also fails (e.g. ConnectionError)
        def head_side_effect(url, *args, **kwargs):
            if url.startswith("https://"):
                raise requests.exceptions.SSLError("HTTPS SSL Error")
            else:
                raise requests.exceptions.ConnectionError("HTTP connection failed")
        mock_head.side_effect = head_side_effect
        mock_get.side_effect = requests.exceptions.ConnectionError("HTTP connection failed")


        from data_acquisition.utils.validation import validate_website_domain
        is_active, healed_url, reason = validate_website_domain('https://rupeek.com')
        self.assertFalse(is_active)
        self.assertIn("HTTPS SSL Error", reason)

    @patch('socket.gethostbyname')
    @patch('requests.get')
    @patch('requests.head')
    def test_validate_website_domain_cloudflare_active(self, mock_head, mock_get, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.3.4'
        
        mock_res = MagicMock()
        mock_res.status_code = 403
        mock_res.__bool__.return_value = False
        mock_res.url = 'https://cloudflare-protected.com'
        mock_res.headers = {'Server': 'cloudflare', 'cf-ray': '123456789'}
        mock_head.return_value = mock_res

        from data_acquisition.utils.validation import validate_website_domain
        is_active, healed_url, reason = validate_website_domain('https://cloudflare-protected.com')
        self.assertTrue(is_active)
        self.assertEqual(healed_url, 'https://cloudflare-protected.com')
        # Since it is a cloudflare response on 403, requests.get shouldn't be called for parking page check
        mock_get.assert_not_called()

    @patch.dict(os.environ, {"MOCK_SCRAPER_FALLBACK": "false"})
    @patch('socket.gethostbyname')
    @patch('requests.get')
    def test_check_job_active_cloudflare(self, mock_get, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.3.4'
        
        # Mock requests.get return 403 with Server: cloudflare
        mock_res = MagicMock()
        mock_res.status_code = 403
        mock_res.__bool__.return_value = False
        mock_res.url = 'https://company.com/jobs/123'
        mock_res.headers = {'Server': 'cloudflare'}
        mock_get.return_value = mock_res

        from data_acquisition.utils.validation import check_job_active
        is_active, reason = check_job_active('https://company.com/jobs/123')
        self.assertTrue(is_active)
        self.assertIn("Cloudflare Protection", reason)

    def test_is_parking_page_helper(self):
        from data_acquisition.utils.validation import is_parking_page
        
        # Title matches + short body -> True
        html_short = "<html><head><title>Hostinger - Domain Parked</title></head><body>Short</body></html>"
        self.assertTrue(is_parking_page(html_short))

        # Title matches + long body + no layout -> True
        html_long_no_layout = "<html><head><title>Domain Parked</title></head><body>" + "A" * 3000 + "</body></html>"
        self.assertTrue(is_parking_page(html_long_no_layout))

        # Title matches + long body + layout (container class) -> False
        html_long_layout = "<html><head><title>Domain Parked</title></head><body><div class=\"container\">" + "A" * 3000 + "</div></body></html>"
        self.assertFalse(is_parking_page(html_long_layout))

        # Title does not match -> False
        html_no_match = "<html><head><title>My Real Startup</title></head><body>Short</body></html>"
        self.assertFalse(is_parking_page(html_no_match))

    @patch.dict(os.environ, {"MOCK_SCRAPER_FALLBACK": "false"})
    @patch('socket.gethostbyname')
    @patch('requests.get')
    def test_check_job_active_parking_page(self, mock_get, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.3.4'
        
        # Mock response returning a parking page HTML
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.url = 'https://expired-startup.com/jobs'
        mock_res.headers = {}
        mock_res.text = "<html><head><title>LiteSpeed Cache</title></head><body>Domain is parked.</body></html>"
        mock_res.content = b"<html><head><title>LiteSpeed Cache</title></head><body>Domain is parked.</body></html>"
        mock_get.return_value = mock_res

        from data_acquisition.utils.validation import check_job_active
        is_active, reason = check_job_active('https://expired-startup.com/jobs')
        self.assertFalse(is_active)
        self.assertIn("Parking page detected", reason)

    @patch('requests.head')
    def test_validate_logo_image_success(self, mock_head):
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.headers = {"Content-Type": "image/png"}
        mock_head.return_value = mock_res

        from data_acquisition.utils.validation import validate_logo_image
        self.assertTrue(validate_logo_image("https://startup.com/logo.png"))

    @patch('requests.get')
    @patch('requests.head')
    def test_validate_logo_image_failure_404_403(self, mock_head, mock_get):
        # HEAD returns 403, GET returns 403
        mock_head_res = MagicMock(status_code=403)
        mock_head.return_value = mock_head_res
        
        mock_get_res = MagicMock(status_code=403)
        mock_get_res.__enter__.return_value = mock_get_res
        mock_get.return_value = mock_get_res

        from data_acquisition.utils.validation import validate_logo_image
        self.assertFalse(validate_logo_image("https://startup.com/logo.png"))
        mock_head.assert_called_once()
        mock_get.assert_called_once()

    @patch('requests.get')
    @patch('requests.head')
    def test_validate_logo_image_failure_non_image(self, mock_head, mock_get):
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.headers = {"Content-Type": "text/html"}
        mock_head.return_value = mock_res
        
        mock_get_res = MagicMock(status_code=200)
        mock_get_res.headers = {"Content-Type": "text/html"}
        mock_get.return_value = mock_get_res

        from data_acquisition.utils.validation import validate_logo_image
        self.assertFalse(validate_logo_image("https://startup.com/logo.png"))

    @patch('requests.head')
    def test_validate_logo_image_rejection_on_timeout(self, mock_head):
        mock_head.side_effect = requests.exceptions.Timeout("Connection timed out")

        from data_acquisition.utils.validation import validate_logo_image
        # Timeout/Connection errors return False
        self.assertFalse(validate_logo_image("https://startup.com/logo.png"))

    @patch('requests.get')
    @patch('requests.head')
    def test_validate_logo_image_head_403_get_200_success(self, mock_head, mock_get):
        mock_head_res = MagicMock(status_code=403)
        mock_head.return_value = mock_head_res

        mock_get_res = MagicMock(status_code=200)
        mock_get_res.headers = {"Content-Type": "image/png"}
        mock_get_res.__enter__.return_value = mock_get_res
        mock_get.return_value = mock_get_res

        from data_acquisition.utils.validation import validate_logo_image
        self.assertTrue(validate_logo_image("https://startup.com/logo.png"))
        mock_head.assert_called_once()
        mock_get.assert_called_once()

    @patch('requests.get')
    @patch('requests.head')
    def test_validate_logo_image_head_405_get_200_success(self, mock_head, mock_get):
        mock_head_res = MagicMock(status_code=405)
        mock_head.return_value = mock_head_res

        mock_get_res = MagicMock(status_code=200)
        mock_get_res.headers = {"Content-Type": "image/jpeg"}
        mock_get_res.__enter__.return_value = mock_get_res
        mock_get.return_value = mock_get_res

        from data_acquisition.utils.validation import validate_logo_image
        self.assertTrue(validate_logo_image("https://startup.com/logo.jpg"))
        mock_head.assert_called_once()
        mock_get.assert_called_once()

    @patch('requests.get')
    @patch('requests.head')
    def test_validate_logo_image_head_403_get_non_image(self, mock_head, mock_get):
        mock_head_res = MagicMock(status_code=403)
        mock_head.return_value = mock_head_res

        mock_get_res = MagicMock(status_code=200)
        mock_get_res.headers = {"Content-Type": "text/html"}
        mock_get_res.__enter__.return_value = mock_get_res
        mock_get.return_value = mock_get_res

        from data_acquisition.utils.validation import validate_logo_image
        self.assertFalse(validate_logo_image("https://startup.com/logo.png"))
        mock_head.assert_called_once()
        mock_get.assert_called_once()

    @patch('requests.get')
    @patch('requests.head')
    def test_validate_logo_image_head_403_get_timeout_rejected(self, mock_head, mock_get):
        mock_head_res = MagicMock(status_code=403)
        mock_head.return_value = mock_head_res

        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out on GET")

        from data_acquisition.utils.validation import validate_logo_image
        self.assertFalse(validate_logo_image("https://startup.com/logo.png"))
        mock_head.assert_called_once()
        mock_get.assert_called_once()

    @patch('requests.get')
    @patch('requests.head')
    def test_validate_logo_image_head_404_no_fallback(self, mock_head, mock_get):
        mock_head_res = MagicMock(status_code=404)
        mock_head.return_value = mock_head_res

        from data_acquisition.utils.validation import validate_logo_image
        self.assertFalse(validate_logo_image("https://startup.com/logo.png"))
        mock_head.assert_called_once()
        mock_get.assert_not_called()

if __name__ == "__main__":
    unittest.main()
