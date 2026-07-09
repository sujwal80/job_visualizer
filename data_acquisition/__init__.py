import os
import sys

_curr_dir = os.path.dirname(os.path.abspath(__file__))
_scrapers_dir = os.path.join(_curr_dir, "job_scrapers")
_tagging_dir = os.path.join(_curr_dir, "tagging")

for _d in [_curr_dir, _scrapers_dir, _tagging_dir]:
    if _d not in sys.path:
        sys.path.append(_d)

from .job_scrapers import *
from .tagging import *

from . import job_scrapers as _js
from . import tagging as _tg

for _mod_name in [
    "linkedin_scraper",
    "instahyre_scraper",
    "yc_scraper",
    "ats_scraper",
    "indeed_scraper",
    "wellfound_scraper",
    "naukri_scraper",
    "glassdoor_scraper",
    "cutshort_scraper",
    "hirist_scraper",
    "job_metadata_extractor",
]:
    if hasattr(_js, _mod_name):
        sys.modules[f"data_acquisition.{_mod_name}"] = getattr(_js, _mod_name)

for _mod_name in [
    "logo_enricher",
    "location_enricher",
    "classify_industries",
    "heal_geocodes",
]:
    if hasattr(_tg, _mod_name):
        sys.modules[f"data_acquisition.{_mod_name}"] = getattr(_tg, _mod_name)
