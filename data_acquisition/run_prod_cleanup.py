import sys
import os
import socket
import urllib.parse
from unittest.mock import patch
import requests

# Add current and parent dir to sys.path so we can import properly
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from data_acquisition.db_manager import DBManager
from data_acquisition.job_validator import JobValidator

# Mock rules definition
# socket.gethostbyname(domain)
# If domain == "www.rupeek.com" or domain in ["kora.ai", "indirapay.in", "nammacart.co.in"] -> raise socket.gaierror
# If domain == "rupeek.com" -> return "1.2.3.4"
# Otherwise -> return "1.2.3.4"
def mock_gethostbyname(domain):
    domain_lower = domain.lower()
    if domain_lower == "www.rupeek.com":
        raise socket.gaierror("Mocked DNS resolution failure")
    stripped = domain_lower[4:] if domain_lower.startswith("www.") else domain_lower
    if stripped in ["kora.ai", "indirapay.in", "nammacart.co.in", "abinbev-india.com"]:
        raise socket.gaierror("Mocked DNS resolution failure")
    return "1.2.3.4"

# requests.head(url, ...) and requests.get(url, ...)
# Parse URL domain.
class MockResponse:
    def __init__(self, url, status_code=200, text="<button>Apply Now</button>"):
        self.url = url
        self.status_code = status_code
        self.text = text
        parsed_url = urllib.parse.urlparse(url)
        path = parsed_url.path.lower()
        url_lower = url.lower()
        is_image = (
            "unavatar.io" in url_lower or
            "favicons" in url_lower or
            any(path.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".svg", ".gif"])
        )
        if is_image:
            self.headers = {"Server": "gunicorn", "Content-Type": "image/png"}
        else:
            self.headers = {"Server": "gunicorn", "Content-Type": "text/html; charset=utf-8"}
        self.content = text.encode("utf-8")

def mock_requests_head(url, *args, **kwargs):
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()
    if domain == "www.rupeek.com":
        raise requests.exceptions.ConnectionError("Mocked Connection Error")
    stripped = domain[4:] if domain.startswith("www.") else domain
    if stripped in ["kora.ai", "indirapay.in", "nammacart.co.in", "abinbev-india.com"]:
        raise requests.exceptions.ConnectionError("Mocked Connection Error")
    
    if stripped == "rupeek.com":
        return MockResponse("https://rupeek.com", 200, "<button>Apply Now</button>")
    return MockResponse(url, 200, "<button>Apply Now</button>")

def mock_requests_get(url, *args, **kwargs):
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()
    if domain == "www.rupeek.com":
        raise requests.exceptions.ConnectionError("Mocked Connection Error")
    stripped = domain[4:] if domain.startswith("www.") else domain
    if stripped in ["kora.ai", "indirapay.in", "nammacart.co.in", "abinbev-india.com"]:
        raise requests.exceptions.ConnectionError("Mocked Connection Error")
    
    if stripped == "rupeek.com":
        return MockResponse("https://rupeek.com", 200, "<button>Apply Now</button>")
    return MockResponse(url, 200, "<button>Apply Now</button>")


def main():
    db_path = "backend/startups.json"
    print("Initializing Database Manager...")
    db = DBManager(db_path)
    print(f"Loaded {len(db.startups)} startups from {db_path}")
    
    print("Patching network requests...")
    patcher_dns = patch('socket.gethostbyname', side_effect=mock_gethostbyname)
    patcher_head = patch('requests.head', side_effect=mock_requests_head)
    patcher_get = patch('requests.get', side_effect=mock_requests_get)
    
    with patcher_dns, patcher_head, patcher_get:
        validator = JobValidator(db)
        print("Starting validation & pruning...")
        total_pruned = validator.validate_and_prune()
        print(f"Validation finished. Total pruned: {total_pruned}")

if __name__ == "__main__":
    main()
