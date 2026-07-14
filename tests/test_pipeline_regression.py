import os
import sys
from unittest.mock import patch, MagicMock

# Add data_acquisition and workspace root to sys.path
workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(workspace_root, "data_acquisition"))
sys.path.append(os.path.join(workspace_root, "data_acquisition", "job_scrapers"))
sys.path.append(os.path.join(workspace_root, "data_acquisition", "tagging"))
sys.path.append(workspace_root)

from logo_enricher import LogoEnricher
from location_enricher import LocationEnricher
from db_manager import DBManager

from yc_scraper import YCScraper
from ats_scraper import ATSScraper
from indeed_scraper import IndeedScraper
from job_validator import JobValidator
from job_metadata_extractor import extract_job_metadata

def test_short_circuiting():
    print("=== TESTING SHORT-CIRCUITING LOGIC ===")
    logo_enricher = LogoEnricher()
    
    # 1. Test Logo Short-Circuit
    startup_with_logo = {
        "name": "TestCorp",
        "logo_domain": "testcorp.com",
        "logo_svg_url": "https://testcorp.com/logo.svg",
        "website": "https://testcorp.com"
    }
    res = logo_enricher.enrich(startup_with_logo)
    assert res is False, "Expected LogoEnricher to short-circuit when logo_domain and logo_svg_url exist!"
    print(" [PASS] LogoEnricher short-circuits correctly when logo_domain exists.")
    
    startup_no_logo = {"name": "NewCorp", "logo_domain": "", "website": "https://newcorp.io"}
    mock_resp = MagicMock(status_code=404)
    with patch("requests.get", return_value=mock_resp):
        res = logo_enricher.enrich(startup_no_logo)
    assert res is True and startup_no_logo["logo_domain"] == "newcorp.io", "Expected LogoEnricher to extract domain from website!"
    assert startup_no_logo["logo_svg_url"] == "", "Expected logo_svg_url to be empty when scraping fails"
    print(" [PASS] LogoEnricher tags logo_domain from website when missing.")

    # 2. Test Location Short-Circuit
    db = DBManager("/tmp/dummy_startups.json")
    loc_enricher = LocationEnricher(db)
    
    startup_with_loc = {"name": "ExactLocCorp", "lat": 12.9357366, "lng": 77.624081}
    res = loc_enricher.enrich(startup_with_loc)
    assert res is False, "Expected LocationEnricher to short-circuit when exact coords exist!"
    print(" [PASS] LocationEnricher short-circuits correctly when exact coords exist.")

def test_sanitization():
    print("\n=== TESTING XSS SANITIZATION ===")
    db = DBManager("/tmp/dummy_startups.json")
    dirty = "<script>alert('XSS')</script>Secure Company <b>Name</b>"
    clean = db._sanitize_string(dirty)
    assert "<script>" not in clean and "<b>" not in clean, f"Sanitization failed! Got: {clean}"
    assert clean == "Secure Company Name" or "alert" in clean
    print(f" [PASS] String sanitization removed HTML/script tags: '{clean}'")

def test_job_validator():
    print("\n=== TESTING JOB VALIDATOR & PRUNING ===")
    db = DBManager("/tmp/test_validator_startups.json")
    db.startups = [
        {
            "id": 999,
            "name": "ExpiredCorp",
            "job_openings": [
                {"title": "Valid Role", "url": "https://www.google.com"}, # Returns 200
                {"title": "Missing URL Role", "url": "N/A"}, # Invalid URL
                {"title": "404 Role", "url": "https://example.com/404"} # Returns 404
            ]
        }
    ]
    validator = JobValidator(db)
    pruned = validator.validate_and_prune()
    remaining = len(db.startups[0]["job_openings"])
    assert pruned == 2 and remaining == 1, f"Expected 2 pruned and 1 remaining, got pruned={pruned}, remaining={remaining}"
    assert db.startups[0]["job_openings"][0]["title"] == "Valid Role"
    print(" [PASS] JobValidator correctly pruned invalid and 404 job postings.")

def test_scrapers_init():
    print("\n=== TESTING SCRAPERS INITIALIZATION ===")
    yc = YCScraper()
    ats = ATSScraper()
    indeed = IndeedScraper()
    print(" [PASS] All multi-source scrapers (YC, ATS, Indeed) initialized cleanly.")

def test_http_429_resilience():
    print("\n=== TESTING HTTP 429 RESILIENCE ===")
    db = DBManager("/tmp/test_429_startups.json")
    validator = JobValidator(db)
    
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    
    with patch("requests.get", return_value=mock_resp):
        is_active, reason = validator._check_job_active("https://example.com/job/123")
        assert is_active is True, f"Expected 429 to be treated as active (resilient), got is_active={is_active}"
        assert "Temporarily Unavailable" in reason or "429" in reason, f"Unexpected reason: {reason}"
    print(" [PASS] HTTP 429 handled resiliently without wrongly pruning job postings.")

def test_null_safety():
    print("\n=== TESTING NULL & MISSING ATTRIBUTE SAFETY ===")
    logo_enricher = LogoEnricher()
    assert logo_enricher.enrich(None) is False, "Expected LogoEnricher to return False for None input"
    null_startup = {"name": None, "logo_domain": None, "website": None, "job_openings": None}
    res = logo_enricher.enrich(null_startup)
    assert res is False, "Expected False when all fields are None"
    
    db = DBManager("/tmp/test_null_db.json")
    db.startups = [{"id": "not_an_int", "name": None, "logo_domain": None}]
    found = db.find_startup(None, None)
    assert found is None or isinstance(found, dict), "find_startup handled None cleanly"
    new_id = db._generate_new_id()
    assert isinstance(new_id, int), "generate_new_id handled non-integer id cleanly"
    print(" [PASS] Null safety and missing attributes handled cleanly without exceptions.")

def test_multi_city_deduplication():
    print("\n=== TESTING MULTI-CITY DEDUPLICATION & COLLISION SCOPING ===")
    db = DBManager("/tmp/test_multicity_db.json")
    db.startups = [
        {
            "id": 1,
            "name": "Apex AI",
            "logo_domain": "apex.ai",
            "city": "Hyderabad, Telangana"
        }
    ]
    res_bengaluru = db.find_startup("Apex AI", "apex.ai", target_city="Bengaluru")
    assert res_bengaluru is None, f"Expected None when searching for Apex AI in Bengaluru, got {res_bengaluru}"
    
    res_hyderabad = db.find_startup("Apex AI", "apex.ai", target_city="Hyderabad")
    assert res_hyderabad is not None and res_hyderabad["id"] == 1, "Expected to find Apex AI in Hyderabad"
    print(" [PASS] Multi-city deduplication scopes company lookups by city without collision.")

def test_scraper_429_backoff_handling():
    print("\n=== TESTING SCRAPER 429 BACKOFF / ERROR HANDLING ===")
    scraper = IndeedScraper()
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    with patch("requests.get", return_value=mock_resp), patch("time.sleep"):
        jobs = scraper.get_bangalore_jobs("TestCorp")
        assert isinstance(jobs, list), f"Expected list return on 429, got {type(jobs)}"
        assert len(jobs) == 0, f"Expected 0 jobs returned on 429 backoff, got {len(jobs)}"
    print(" [PASS] Scraper gracefully returns empty list on HTTP 429 without raising exceptions.")

def test_db_manager_null_record_handling():
    print("\n=== TESTING DB MANAGER NULL RECORD HANDLING ===")
    db = DBManager("/tmp/test_null_records_db.json")
    db.startups = []
    company_details = {"name": None, "website": None, "logo_domain": None, "description": None}
    with patch.object(db, "geocode_address", return_value=(None, None)):
        db.merge_startup(company_details, [None, {"title": None, "url": None}], target_city="Hyderabad")
    assert len(db.startups) == 1, "Expected 1 startup created despite null attributes"
    assert db.startups[0]["name"] == "N/A" or db.startups[0]["name"] is None or db.startups[0]["name"] == "None", f"Got name: {db.startups[0]['name']}"
    print(" [PASS] DBManager merge_startup handles null records and jobs safely.")

def test_multi_city_merge_isolation():
    print("\n=== TESTING MULTI-CITY MERGE ISOLATION ===")
    db = DBManager("/tmp/test_multicity_merge_db.json")
    db.startups = [
        {
            "id": 1,
            "name": "Apex AI",
            "logo_domain": "apex.ai",
            "city": "Hyderabad, Telangana",
            "job_openings": []
        }
    ]
    mock_response = MagicMock(status_code=200, url="http://apex.ai/job", text="<html><body><button>Apply Now</button></body></html>")
    with patch.object(db, "geocode_address", return_value=(12.9716, 77.5946)), \
         patch("requests.get", return_value=mock_response):
        db.merge_startup({"name": "Apex AI", "logo_domain": "apex.ai"}, [{"title": "Eng", "url": "http://apex.ai/job"}], target_city="Bengaluru")
    
    assert len(db.startups) == 2, f"Expected 2 separate startup records for different cities, got {len(db.startups)}"
    hyd_startup = [s for s in db.startups if "Hyderabad" in str(s.get("city"))][0]
    blr_startup = [s for s in db.startups if "Bengaluru" in str(s.get("city")) or "Bangalore" in str(s.get("city")) or s.get("id") == 2][0]
    assert len(hyd_startup.get("job_openings", [])) == 0, "Hyderabad company should not have received the Bengaluru job!"
    assert len(blr_startup.get("job_openings", [])) == 1, "Bengaluru company should have received the job!"
    print(" [PASS] Multi-city merge isolates companies by target city without overwriting.")

from indeed_scraper import IndeedScraper
from wellfound_scraper import WellfoundScraper
from naukri_scraper import NaukriScraper
from glassdoor_scraper import GlassdoorScraper
from cutshort_scraper import CutshortScraper
from hirist_scraper import HiristScraper

def test_universal_scrapers_init():
    print("\n=== TESTING UNIVERSAL SCRAPERS INITIALIZATION & PARSING ===")
    indeed = IndeedScraper()
    wellfound = WellfoundScraper()
    naukri = NaukriScraper()
    glassdoor = GlassdoorScraper()
    cutshort = CutshortScraper()
    hirist = HiristScraper()
    
    assert hasattr(indeed, "get_bangalore_jobs"), "IndeedScraper missing get_bangalore_jobs"
    assert hasattr(wellfound, "get_bangalore_jobs"), "WellfoundScraper missing get_bangalore_jobs"
    assert hasattr(naukri, "get_bangalore_jobs"), "NaukriScraper missing get_bangalore_jobs"
    assert hasattr(glassdoor, "get_bangalore_jobs"), "GlassdoorScraper missing get_bangalore_jobs"
    assert hasattr(cutshort, "get_bangalore_jobs"), "CutshortScraper missing get_bangalore_jobs"
    assert hasattr(hirist, "get_bangalore_jobs"), "HiristScraper missing get_bangalore_jobs"
    print(" [PASS] All 6 universal scrapers initialized cleanly with verified interfaces.")

def test_deep_html_apply_inspection():
    print("\n=== TESTING DEEP HTML APPLY-ABILITY INSPECTION ===")
    try:
        from utils.validation import inspect_html_content
    except ImportError:
        from data_acquisition.utils.validation import inspect_html_content
    
    # Positive case 1: Apply button text
    html_apply_btn = '<html><body><div class="job-header"><h1>Software Engineer</h1><a href="/apply/123" class="btn">Apply Now</a></div></body></html>'
    assert inspect_html_content(html_apply_btn, "https://example.com/job/123") is True, "Expected Apply Now button text to pass deep inspection"
    
    # Positive case 2: Application form endpoint
    html_form = '<html><body><form action="https://example.com/submit-application" method="POST"><input type="text" name="resume"/></form></body></html>'
    assert inspect_html_content(html_form, "https://example.com/job/form") is True, "Expected form submit-application endpoint to pass deep inspection"
    
    # Positive case 3: ATS embed URL
    html_ats = '<html><body><iframe src="https://boards.greenhouse.io/embed/job_app"></iframe></body></html>'
    assert inspect_html_content(html_ats, "https://example.com/careers/role") is True, "Expected Greenhouse ATS embed to pass deep inspection"
    
    # Negative case: Generic homepage landing trap
    html_trap = '<html><head><title>Welcome to Corp</title></head><body><h1>About Us</h1><p>We are a leading software solutions provider.</p></body></html>'
    assert inspect_html_content(html_trap, "https://example.com/careers") is False, "Expected generic homepage landing trap to fail deep inspection"
    print(" [PASS] Deep HTML apply-ability inspection correctly distinguished true apply pages from generic homepage traps.")

def test_universal_scrapers():
    print("\n=== TESTING UNIVERSAL SCRAPERS EXECUTION ===")
    mock_resp = MagicMock(status_code=200, text="<html></html>")
    with patch("requests.get", return_value=mock_resp), patch("requests.request", return_value=mock_resp):
        scrapers = [
            IndeedScraper(),
            WellfoundScraper(),
            NaukriScraper(),
            GlassdoorScraper(),
            CutshortScraper(),
            HiristScraper()
        ]
        for scraper in scrapers:
            jobs = scraper.get_bangalore_jobs("Test")
            assert isinstance(jobs, list), f"{scraper.__class__.__name__}.get_bangalore_jobs did not return a list!"
    print(" [PASS] Calling get_bangalore_jobs('Test') on all 6 universal scrapers returns a list.")

def test_deep_apply_ability_validation():
    print("\n=== TESTING DEEP APPLY-ABILITY VALIDATION ===")
    db = DBManager("/tmp/test_deep_apply_validation.json")
    validator = JobValidator(db)

    # 1. Valid apply link with <button>Apply Now</button>
    mock_apply_btn = MagicMock(status_code=200, url="https://example.com/job/1", text="<html><body><button>Apply Now</button></body></html>")
    with patch("requests.get", return_value=mock_apply_btn):
        is_active, reason = validator._check_job_active("https://example.com/job/1")
        assert is_active is True, f"Expected active job for HTML with Apply Now button, got {is_active} ({reason})"

    # 2. Valid apply link with ATS domain
    mock_ats = MagicMock(status_code=200, url="https://example.com/job/2", text="<html><body><iframe src=\"https://boards.greenhouse.io/embed\"></iframe></body></html>")
    with patch("requests.get", return_value=mock_ats):
        is_active, reason = validator._check_job_active("https://example.com/job/2")
        assert is_active is True, f"Expected active job for ATS domain embed, got {is_active} ({reason})"

    # 3. Generic trap / expired notice lacking apply mechanisms
    mock_trap = MagicMock(status_code=200, url="https://example.com/job/3", text="<html><body>Welcome to careers. Position has been filled or no apply mechanism found.</body></html>")
    with patch("requests.get", return_value=mock_trap):
        is_active, reason = validator._check_job_active("https://example.com/job/3")
        assert is_active is False, f"Expected inactive job for generic trap/expired notice, got {is_active} ({reason})"

    print(" [PASS] JobValidator._check_job_active correctly distinguishes valid apply links from generic traps.")

def test_inline_job_metadata_extraction():
    print("\n=== TESTING INLINE JOB METADATA EXTRACTION ===")
    
    # Test case 1: Full inline metadata string
    title1 = "Senior Python Developer (3-5 yrs) - ₹15L - ₹20L LPA"
    snippet1 = "We are hiring for an Internship role requiring Python, React, Node, and AWS."
    res1 = extract_job_metadata(title1, snippet1)
    assert res1["experience"] == "3-5 yrs", f"Expected '3-5 yrs', got {res1['experience']}"
    assert res1["salary"] == "₹15L - ₹20L LPA", f"Expected '₹15L - ₹20L LPA', got {res1['salary']}"
    assert res1["job_type"] == "Internship", f"Expected 'Internship', got {res1['job_type']}"
    assert set(res1["skills"]) == {"Python", "React", "Node", "AWS"}, f"Expected Python, React, Node, AWS, got {res1['skills']}"
    print(" [PASS] Extracted experience, salary, job type, and tech stack skills accurately from inline text.")

    # Test case 2: API dictionary parsing & fallbacks
    extra2 = {"min_exp": 2, "max_exp": 4, "employment_type": "Full-time", "skills": ["Docker"]}
    res2 = extract_job_metadata("Backend Engineer", "Salary: 18 - 25 LPA", extra_data=extra2)
    assert res2["experience"] == "2-4 yrs", f"Expected '2-4 yrs', got {res2['experience']}"
    assert res2["salary"] == "18 - 25 LPA", f"Expected '18 - 25 LPA', got {res2['salary']}"
    assert res2["job_type"] == "Full-time", f"Expected 'Full-time', got {res2['job_type']}"
    assert "Docker" in res2["skills"], f"Expected Docker in skills, got {res2['skills']}"
    assert res2["posted_date"] == "Recent", f"Expected 'Recent', got {res2['posted_date']}"
    
    res3 = extract_job_metadata("Frontend Role", "Posted 2 days ago")
    assert res3["posted_date"] == "Posted 2 days ago", f"Expected 'Posted 2 days ago', got {res3['posted_date']}"
    print(" [PASS] Extracted metadata using API dictionary parsing and regex fallback cleanly.")

def test_candidate_validation_features():
    print("\n=== TESTING CANDIDATE VALIDATION FEATURES ===")
    db = DBManager("/tmp/test_candidate_validation.json")
    validator = JobValidator(db)
    
    # Test valid email syntax
    s1 = {"name": "TestCorp", "hr_details": {"contact_email": "careers@testcorp.io"}, "website": "https://www.google.com"}
    validator.validate_company_status(s1)
    assert s1["verified_email"] == "careers@testcorp.io", f"Expected verified email, got {s1['verified_email']}"
    assert s1["is_active_website"] is True, f"Expected active website, got {s1['is_active_website']}"
    
    # Test invalid email syntax
    s2 = {"name": "BadEmail", "hr_details": {"contact_email": "not-an-email"}, "website": "N/A"}
    validator.validate_company_status(s2)
    assert s2["verified_email"] == "", f"Expected empty verified email for invalid syntax, got {s2['verified_email']}"
    print(" [PASS] Candidate validation features verified email syntax and website status cleanly.")

def test_metadata_cleaning_on_dead_website():
    print("\n=== TESTING METADATA AUTO-CLEANING ON DEAD WEBSITE ===")
    db = DBManager("/tmp/test_metadata_cleaning.json")
    validator = JobValidator(db)
    
    startup = {
        "name": "DeadCorp",
        "website": "https://deadcorp.com",
        "logo_svg_url": "https://deadcorp.com/logo.svg",
        "verified_email": "careers@deadcorp.com",
        "hr_details": {"contact_email": "careers@deadcorp.com"}
    }
    
    with patch("job_validator.validate_website_domain", return_value=(False, "https://deadcorp.com", "DNS failed")):
        validator.validate_company_status(startup)
        
    assert startup["is_active_website"] is False
    assert startup["logo_svg_url"] == ""
    assert startup["verified_email"] == ""
    print(" [PASS] Metadata auto-cleaning on dead website cleared logo_svg_url and verified_email.")

def test_logo_validation_for_active_website():
    print("\n=== TESTING LOGO IMAGE VALIDATION FOR ACTIVE WEBSITE ===")
    db = DBManager("/tmp/test_logo_val.json")
    validator = JobValidator(db)
    
    # Case A: validate_logo_image returns False -> clear logo_svg_url
    startup_a = {
        "name": "ActiveCorpA",
        "website": "https://activecorp.com",
        "logo_svg_url": "https://activecorp.com/bad_logo.svg",
        "is_active_website": True
    }
    
    with patch("job_validator.validate_website_domain", return_value=(True, "https://activecorp.com", None)), \
         patch("job_validator.validate_logo_image", return_value=False):
        validator.validate_company_status(startup_a)
        
    assert startup_a["is_active_website"] is True
    assert startup_a["logo_svg_url"] == ""
    
    # Case B: validate_logo_image returns True -> keep logo_svg_url
    startup_b = {
        "name": "ActiveCorpB",
        "website": "https://activecorp.com",
        "logo_svg_url": "https://activecorp.com/good_logo.svg",
        "is_active_website": True
    }
    
    with patch("job_validator.validate_website_domain", return_value=(True, "https://activecorp.com", None)), \
         patch("job_validator.validate_logo_image", return_value=True):
        validator.validate_company_status(startup_b)
        
    assert startup_b["is_active_website"] is True
    assert startup_b["logo_svg_url"] == "https://activecorp.com/good_logo.svg"
    print(" [PASS] Logo image validation for active website correctly prunes or retains logo_svg_url.")

def test_ingestion_gates():
    print("\n=== TESTING INGESTION GATES (MILESTONE 3) ===")
    from db_manager import DBManager
    from discovery_service import CompanyDiscoveryService
    
    # 1. Case 1: Dead Website + No Active Jobs -> returns None, not merged
    db = DBManager("/tmp/test_ingestion_gates.json")
    db.startups = []
    
    company_details = {
        "name": "DeadNoJobsCorp",
        "website": "https://deadnojobs.com",
        "logo_svg_url": "https://deadnojobs.com/logo.svg",
        "logo_domain": "deadnojobs.com",
        "verified_email": "hr@deadnojobs.com",
        "is_active_website": False,
        "hr_details": {"contact_email": "hr@deadnojobs.com"}
    }
    
    jobs = [{"title": "Software Engineer", "url": "https://deadnojobs.com/jobs/1"}]
    
    with patch("db_manager.check_job_active", return_value=(False, "Closed")):
        result = db.merge_startup(company_details, jobs)
        assert result is None, f"Expected merge_startup to return None for dead website and no active jobs, got {result}"
        assert len(db.startups) == 0, f"Expected 0 startups in DB, got {len(db.startups)}"
    print(" [PASS] Case 1: Dead Website + No Active Jobs rejected successfully.")

    # 2. Case 2: Dead Website + Active Jobs -> merged successfully, logo/email fields cleared, website marked inactive
    db = DBManager("/tmp/test_ingestion_gates.json")
    db.startups = []
    
    company_details = {
        "name": "DeadWithJobsCorp",
        "website": "https://deadwithjobs.com",
        "logo_svg_url": "https://deadwithjobs.com/logo.svg",
        "logo_domain": "deadwithjobs.com",
        "verified_email": "hr@deadwithjobs.com",
        "is_active_website": False,
        "hr_details": {"contact_email": "hr@deadwithjobs.com"}
    }
    
    jobs = [{"title": "Software Engineer", "url": "https://deadwithjobs.com/jobs/1"}]
    
    with patch.object(db, "geocode_address", return_value=(12.9, 77.6)), \
         patch("db_manager.check_job_active", return_value=(True, "Active")):
        result = db.merge_startup(company_details, jobs)
        assert result is not None, "Expected merge_startup to return merged startup record"
        assert result["is_active_website"] is False, "Expected website to remain inactive"
        assert result["logo_svg_url"] == "", f"Expected logo_svg_url to be cleared, got {result['logo_svg_url']}"
        assert result["logo_domain"] == "", f"Expected logo_domain to be cleared, got {result['logo_domain']}"
        assert result["verified_email"] == "", f"Expected verified_email to be cleared, got {result['verified_email']}"
        assert result["hr_details"]["contact_email"] == "", f"Expected contact_email to be cleared, got {result['hr_details']['contact_email']}"
        assert len(db.startups) == 1, "Expected startup to be added to DB"
    print(" [PASS] Case 2: Dead Website + Active Jobs merged & cleared successfully.")

    # 3. Case 3: Active Website -> merged successfully with logo/email preserved
    db = DBManager("/tmp/test_ingestion_gates.json")
    db.startups = []
    
    company_details = {
        "name": "ActiveCorp",
        "website": "https://activecorp.com",
        "logo_svg_url": "https://activecorp.com/logo.svg",
        "logo_domain": "activecorp.com",
        "verified_email": "hr@activecorp.com",
        "is_active_website": True,
        "hr_details": {"contact_email": "hr@activecorp.com"}
    }
    
    jobs = [{"title": "Software Engineer", "url": "https://activecorp.com/jobs/1"}]
    
    with patch.object(db, "geocode_address", return_value=(12.9, 77.6)), \
         patch("db_manager.check_job_active", return_value=(True, "Active")):
        result = db.merge_startup(company_details, jobs)
        assert result is not None, "Expected merge_startup to return merged startup record"
        assert result["is_active_website"] is True
        assert result["logo_domain"] == "activecorp.com", f"Expected logo_domain to be preserved, got {result['logo_domain']}"
        assert result["verified_email"] == "hr@activecorp.com", f"Expected verified_email to be preserved, got {result['verified_email']}"
        assert len(db.startups) == 1, "Expected startup to be added to DB"
    print(" [PASS] Case 3: Active Website merged and preserved successfully.")

    # 4. Case 4: Discovery service integration -> does not save DB or increment count when merge_startup returns None
    db = DBManager("/tmp/test_ingestion_gates.json")
    db.startups = []
    
    mock_scraper = MagicMock()
    mock_scraper.get_jobs.return_value = [{"company_name": "DeadNoJobsCorp", "title": "Eng", "url": "https://deadnojobs.com/job"}]
    mock_validator = MagicMock()
    
    service = CompanyDiscoveryService(db, mock_scraper, validator=mock_validator)
    
    with patch.object(db, "merge_startup", return_value=None), \
         patch.object(db, "save_db") as mock_save:
        service.discover_new_companies(keywords_list=["TestKW"], max_new_companies=1, target_city="Bengaluru")
        assert mock_save.call_count == 0, "Expected db.save_db to NOT be called when merge_startup returns None"
    print(" [PASS] Case 4: Discovery Service Integration verified successfully.")

if __name__ == "__main__":
    test_short_circuiting()
    test_sanitization()
    test_job_validator()
    test_scrapers_init()
    test_http_429_resilience()
    test_null_safety()
    test_multi_city_deduplication()
    test_scraper_429_backoff_handling()
    test_db_manager_null_record_handling()
    test_multi_city_merge_isolation()
    test_universal_scrapers_init()
    test_deep_html_apply_inspection()
    test_universal_scrapers()
    test_deep_apply_ability_validation()
    test_inline_job_metadata_extraction()
    test_candidate_validation_features()
    test_metadata_cleaning_on_dead_website()
    test_logo_validation_for_active_website()
    test_ingestion_gates()
    print("\nALL VERIFICATION TESTS PASSED SUCCESSFULLY!")
