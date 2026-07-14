import os
import sys

_curr_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_curr_dir)
if _curr_dir not in sys.path:
    sys.path.append(_curr_dir)
if _parent_dir not in sys.path:
    sys.path.append(_parent_dir)

from .linkedin_scraper import LinkedInScraper
from .instahyre_scraper import InstahyreScraper
from .yc_scraper import YCScraper
from .ats_scraper import ATSScraper
from .indeed_scraper import IndeedScraper
from .wellfound_scraper import WellfoundScraper
from .naukri_scraper import NaukriScraper
from .glassdoor_scraper import GlassdoorScraper
from .cutshort_scraper import CutshortScraper
from .hirist_scraper import HiristScraper
from .job_metadata_extractor import extract_job_metadata
from .scraper_base import ScraperBase

__all__ = [
    "LinkedInScraper",
    "InstahyreScraper",
    "YCScraper",
    "ATSScraper",
    "IndeedScraper",
    "WellfoundScraper",
    "NaukriScraper",
    "GlassdoorScraper",
    "CutshortScraper",
    "HiristScraper",
    "extract_job_metadata",
    "ScraperBase",
]
