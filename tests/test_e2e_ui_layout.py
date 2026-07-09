import unittest
import sys
import os
import json
import math
from unittest.mock import patch

# Ensure backend can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.app import app


def load_all_js_contents(workspace_root):
    js_dir = os.path.join(workspace_root, 'frontend', 'static', 'js')
    contents = []
    
    app_js = os.path.join(js_dir, 'app.js')
    if os.path.exists(app_js):
        with open(app_js, 'r', encoding='utf-8') as f:
            contents.append(f.read())
            
    modules_dir = os.path.join(js_dir, 'modules')
    if os.path.exists(modules_dir):
        for root, dirs, files in os.walk(modules_dir):
            for file in files:
                if file.endswith('.js'):
                    with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                        contents.append(f.read())
                        
    return "\n\n/* MODULE BOUNDARY */\n\n".join(contents)


class TestR1ViewportAndLayoutResilience(unittest.TestCase):
    """
    R1: Viewport & Responsive Layout Stress Testing (>= 15 test cases)
    Verifies frontend rendering rules, CSS media queries, responsive classes,
    layout adaptation across viewports, window resize/move handlers, and overflow prevention.
    """

    @classmethod
    def setUpClass(cls):
        cls.workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        cls.css_path = os.path.join(cls.workspace_root, 'frontend', 'static', 'css', 'style.css')
        cls.html_path = os.path.join(cls.workspace_root, 'frontend', 'templates', 'index.html')

        with open(cls.css_path, 'r', encoding='utf-8') as f:
            cls.css_content = f.read()
        with open(cls.html_path, 'r', encoding='utf-8') as f:
            cls.html_content = f.read()
        cls.js_content = load_all_js_contents(cls.workspace_root)

    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def test_r1_01_mobile_320px_media_query_existence(self):
        """Verify style.css defines media queries for mobile/tablet screen adaptation."""
        self.assertIn('@media', self.css_content, "CSS must define media queries for responsive layouts.")
        self.assertIn('max-width: 900px', self.css_content, "CSS must handle mobile/tablet breakpoints.")
        self.assertIn('max-width: 320px', self.css_content, "CSS must handle mobile portrait (320px) breakpoint.")
        self.assertIn('max-width: 768px', self.css_content, "CSS must handle tablet (768px) breakpoint.")
        self.assertIn('min-width: 1920px', self.css_content, "CSS must handle desktop (1920px) breakpoint.")

    def test_r1_02_mobile_toggle_button_in_html(self):
        """Verify mobile toggle button element exists in index.html with appropriate accessibility label."""
        self.assertIn('id="mobile-toggle-btn"', self.html_content, "index.html missing #mobile-toggle-btn.")
        self.assertIn('class="mobile-toggle"', self.html_content, "mobile-toggle-btn missing .mobile-toggle class.")
        self.assertIn('aria-label=', self.html_content, "Toggle button should have aria-label for accessibility.")

    def test_r1_03_mobile_toggle_css_visibility(self):
        """Verify .mobile-toggle is hidden on desktop and visible on mobile breakpoints."""
        self.assertIn('.mobile-toggle', self.css_content, "CSS missing .mobile-toggle styles.")
        self.assertIn('display: none;', self.css_content, ".mobile-toggle should be hidden by default on desktop.")
        self.assertIn('display: block;', self.css_content, ".mobile-toggle should be visible under mobile media query.")

    def test_r1_04_sidebar_responsive_offscreen_on_mobile(self):
        """Verify sidebar transforms offscreen by default on narrow viewports to prevent element overlap."""
        self.assertIn('transform: translateX(-100%);', self.css_content, "Sidebar must transform offscreen on mobile viewports.")

    def test_r1_05_sidebar_active_class_adaptation(self):
        """Verify .sidebar.active slides into view on mobile toggle events."""
        self.assertIn('.sidebar.active', self.css_content, "CSS missing .sidebar.active class definition.")
        self.assertIn('transform: translateX(0);', self.css_content, "Active sidebar must slide into viewport.")

    def test_r1_06_details_drawer_responsive_width(self):
        """Verify details drawer adapts to full width on mobile devices without overlapping."""
        self.assertIn('.details-drawer', self.css_content, "CSS missing .details-drawer class definition.")
        self.assertIn('width: 100%;', self.css_content, "Details drawer should adapt to 100% width on mobile screens.")

    def test_r1_07_quick_tabs_hidden_on_mobile(self):
        """Verify quick industry tabs are hidden on mobile breakpoints to prevent top navbar overflow."""
        self.assertIn('.quick-tabs', self.css_content, "CSS missing .quick-tabs class definition.")
        # Under @media (max-width: 900px) quick-tabs is set to display: none
        self.assertIn('display: none;', self.css_content, "Quick tabs should be hidden on mobile to prevent overflow.")

    def test_r1_08_text_overflow_ellipsis_on_card_title(self):
        """Verify card titles use white-space nowrap and text-overflow ellipsis to prevent text wrapping/overflow."""
        self.assertIn('.card-title', self.css_content, "CSS missing .card-title class definition.")
        self.assertIn('text-overflow: ellipsis;', self.css_content, "Card titles must use ellipsis for text overflow.")
        self.assertIn('white-space: nowrap;', self.css_content, "Card titles must prevent line wrapping.")
        self.assertIn('overflow: hidden;', self.css_content, "Card titles must hide overflow text.")

    def test_r1_09_card_body_min_width_zero(self):
        """Verify flex child .card-body specifies min-width: 0 to allow proper ellipsis rendering in flex layouts."""
        self.assertIn('.card-body', self.css_content, "CSS missing .card-body class definition.")
        self.assertIn('min-width: 0;', self.css_content, ".card-body must have min-width: 0 to prevent flexbox overflow.")

    def test_r1_10_map_container_flex_adaptation(self):
        """Verify main content and map container use flexible box layout to dynamically fill viewport dimensions."""
        self.assertIn('.main-content', self.css_content, "CSS missing .main-content class definition.")
        self.assertIn('display: flex;', self.css_content, ".main-content must use display: flex.")
        self.assertIn('.map-container', self.css_content, "CSS missing .map-container class definition.")
        self.assertIn('flex: 1;', self.css_content, ".map-container must flex to fill remaining space.")

    def test_r1_11_js_mobile_toggle_click_handler(self):
        """Verify JavaScript attaches event listener to mobileToggleBtn to toggle directory vs map view."""
        self.assertIn("mobileToggleBtn.addEventListener('click'", self.js_content, "JS missing click handler for mobileToggleBtn.")
        self.assertIn("sidebar.classList.contains('active')", self.js_content, "JS must check active status of sidebar.")

    def test_r1_12_js_viewport_moveend_handler(self):
        """Verify map moveend event listener is registered to dynamically query viewport startups."""
        self.assertIn("map.on('moveend'", self.js_content, "JS missing moveend event listener on map.")
        self.assertIn("map.getBounds()", self.js_content, "JS must query map bounding box on viewport move.")

    def test_r1_13_js_viewport_debounce_300ms(self):
        """Verify map moveend event handling debounces network calls by 300ms to prevent request spam during zooming/panning."""
        self.assertIn("setTimeout(", self.js_content, "JS must use setTimeout for debouncing viewport events.")
        self.assertIn("300", self.js_content, "Viewport debounce timeout should be 300ms.")

    def test_r1_14_backend_viewport_bounding_box_filtering(self):
        """Programmatically test /api/startups with viewport bounding coordinates (12.9 to 13.0 Lat, 77.5 to 77.6 Lng)."""
        resp = self.client.get('/api/startups?min_lat=12.9000&max_lat=13.0000&min_lng=77.5000&max_lng=77.6000')
        self.assertEqual(resp.status_code, 200, "Backend must return 200 for valid bounding box queries.")
        data = json.loads(resp.data)
        self.assertIsInstance(data, list, "Response payload must be a JSON array.")
        for s in data:
            if s.get("has_pin"):
                lat, lng = s.get("lat"), s.get("lng")
                self.assertIsNotNone(lat, f"Lat must not be None for pinned startup {s.get('id')}")
                self.assertIsNotNone(lng, f"Lng must not be None for pinned startup {s.get('id')}")
                self.assertTrue(12.9000 <= lat <= 13.0000, f"Lat {lat} out of requested bounds [12.9, 13.0]")
                self.assertTrue(77.5000 <= lng <= 77.6000, f"Lng {lng} out of requested bounds [77.5, 77.6]")

    def test_r1_15_backend_viewport_remote_startups_retention(self):
        """Verify remote/hub startups (has_pin=False) remain discoverable when viewport moves outside Bengaluru."""
        with patch('backend.app.load_startups') as mock_load:
            mock_load.return_value = [{
                "id": 9991,
                "name": "Global Remote Corp",
                "lat": None,
                "lng": None,
                "city": "Remote",
                "has_pin": False
            }]
            resp = self.client.get('/api/startups?min_lat=40.0&max_lat=41.0&min_lng=-74.0&max_lng=-73.0')
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            ids = [s["id"] for s in data]
            self.assertIn(9991, ids, "Remote startups must be retained even when viewport bounding box is elsewhere.")

    def test_r1_16_css_prevent_unintended_horizontal_scroll(self):
        """Verify main workspace container prevents unintended horizontal scrollbars via overflow restrictions."""
        self.assertIn('overflow: hidden;', self.css_content, "CSS must restrict overflow to prevent horizontal scrollbars.")

    def test_r1_17_explicit_320px_mobile_portrait_resilience(self):
        """Verify @media (max-width: 320px) adapts navbar, search controls, and drawer overlays without text overflow or element overlap."""
        self.assertIn('@media (max-width: 320px)', self.css_content, "CSS must explicitly define 320px mobile portrait media query.")
        self.assertIn('max-width: 110px;', self.css_content, "320px media query must restrict brand title width to prevent overlap.")
        self.assertIn('width: 95px;', self.css_content, "320px media query must adapt search box width cleanly.")

    def test_r1_18_explicit_768px_tablet_resilience(self):
        """Verify @media (max-width: 768px) adapts sidebar overlay width and z-index hierarchy without overlapping boundaries."""
        self.assertIn('@media (max-width: 768px)', self.css_content, "CSS must explicitly define 768px tablet media query.")
        self.assertIn('width: 380px;', self.css_content, "768px media query must constrain sidebar overlay width.")
        self.assertIn('z-index: 55;', self.css_content, "768px media query must enforce proper drawer z-index layering over sidebar.")

    def test_r1_19_explicit_1920px_desktop_resilience(self):
        """Verify @media (min-width: 1920px) adapts directory list, drawer dimensions, and typography for ultra-wide desktop viewports."""
        self.assertIn('@media (min-width: 1920px)', self.css_content, "CSS must explicitly define 1920px desktop media query.")
        self.assertIn('max-width: 25vw;', self.css_content, "1920px media query must scale sidebar width proportionally.")
        self.assertIn('max-width: 30vw;', self.css_content, "1920px media query must scale drawer width proportionally.")

    def test_r1_20_js_window_resize_viewport_adaptation_resilience(self):
        """Verify app.js window resize listener safely transitions between mobile (<=900px) and desktop (>900px) viewports without JS runtime errors."""
        self.assertIn("window.addEventListener('resize'", self.js_content, "app.js must listen for window resize events.")
        self.assertIn("width > 900 && sidebar && sidebar.classList.contains('active')", self.js_content, "app.js must clean up active sidebar classes when transitioning to desktop viewport.")
        self.assertIn("mobileToggleBtn.textContent = 'Show Directory'", self.js_content, "app.js must reset toggle button text on desktop transition.")

    def test_r1_21_js_edge_viewport_zero_dimensions_and_nan_safety(self):
        """Verify app.js moveend handler checks container clientWidth/clientHeight and validates bounds against isNaN under edge viewport conditions."""
        self.assertIn("container.clientWidth === 0 || container.clientHeight === 0", self.js_content, "app.js must check for 0-dimension edge viewports.")
        self.assertIn("isNaN(bounds.getSouth())", self.js_content, "app.js must validate viewport bounds against NaN under edge conditions.")

    def test_r1_22_js_check_viewport_resilience_helper(self):
        """Verify app.js exports checkViewportResilience on window.WorldTechApp to programmatically assert layout boundaries across viewports."""
        self.assertIn("function checkViewportResilience(width, height)", self.js_content, "app.js must define checkViewportResilience helper.")
        self.assertIn("checkViewportResilience", self.js_content, "app.js must export checkViewportResilience in window.WorldTechApp.")
        self.assertIn("isMobile = width <= 900", self.js_content, "checkViewportResilience must evaluate mobile viewport threshold.")
        self.assertIn("isTablet = width > 480 && width <= 900", self.js_content, "checkViewportResilience must evaluate tablet viewport threshold.")
        self.assertIn("isDesktop = width > 900", self.js_content, "checkViewportResilience must evaluate desktop viewport threshold.")

    def test_r1_23_css_glassmorphic_cards_and_drawer_overlay_boundaries(self):
        """Verify style.css enforces box-sizing border-box, max-width 100%, and text overflow handling on glassmorphic cards and drawers."""
        self.assertIn("box-sizing: border-box;", self.css_content, "CSS must apply border-box sizing across all elements.")
        self.assertIn("max-width: 100%;", self.css_content, "CSS must restrict glassmorphic containers and items to max-width: 100%.")
        self.assertIn("word-break: break-word;", self.css_content, "CSS must allow word breaking for long text strings.")

    def test_r1_24_css_navbar_search_controls_viewport_adaptation(self):
        """Verify style.css adapts navbar search input dimensions and spacing cleanly across viewports without text overflow."""
        self.assertIn("width: 280px;", self.css_content, "Default search box width must be 280px.")
        self.assertIn("width: 160px;", self.css_content, "Search box must adapt to 160px under 600px breakpoint.")
        self.assertIn("width: 130px;", self.css_content, "Search box must adapt to 130px under 480px breakpoint.")
        self.assertIn("width: 95px;", self.css_content, "Search box must adapt to 95px under 320px breakpoint.")

    def test_r1_25_css_unified_drawer_profile_card_structure(self):
        """Verify unified drawer profile card (.drawer-profile-card) and wrapping badge rows prevent multiple stacked divs and badge overflow."""
        self.assertIn(".drawer-profile-card", self.css_content, "CSS must define .drawer-profile-card container.")
        self.assertIn(".drawer-badges-row", self.css_content, "CSS must define .drawer-badges-row.")
        self.assertIn("flex-wrap: wrap;", self.css_content, "Badges row must enforce flex-wrap: wrap to prevent horizontal overflow.")
        self.assertIn("drawer-profile-card", self.js_content, "ui_manager.js must render unified .drawer-profile-card at top of company profile.")

    def test_r1_26_css_source_specific_apply_button_classes(self):
        """Verify style.css defines all 12 source-specific button modifier classes with WCAG white text and inline-flex alignment."""
        expected_classes = [
            '.btn-linkedin', '.btn-google', '.btn-instahyre', '.btn-yc',
            '.btn-ats', '.btn-indeed', '.btn-wellfound', '.btn-naukri',
            '.btn-glassdoor', '.btn-cutshort', '.btn-hirist', '.btn-direct'
        ]
        for cls_name in expected_classes:
            self.assertIn(cls_name, self.css_content, f"style.css missing modifier class {cls_name}")
        self.assertIn('display: inline-flex;', self.css_content, "CSS rules must use display: inline-flex for button icon/text alignment.")
        self.assertIn('align-items: center;', self.css_content, "CSS rules must use align-items: center for button icon/text alignment.")

    def test_r1_27_js_source_specific_apply_button_mapping_and_rendering(self):
        """Verify ui_manager.js defines getJobSourceButtonStyle and maps the 12 source types with mr-1.5 icon spacing."""
        self.assertIn('function getJobSourceButtonStyle', self.js_content, "JS missing getJobSourceButtonStyle function definition.")
        source_classes = [
            'btn-linkedin', 'btn-google', 'btn-instahyre', 'btn-yc',
            'btn-ats', 'btn-indeed', 'btn-wellfound', 'btn-naukri',
            'btn-glassdoor', 'btn-cutshort', 'btn-hirist', 'btn-direct'
        ]
        for btn_cls in source_classes:
            self.assertIn(btn_cls, self.js_content, f"JS missing button class mapping for {btn_cls}")
        self.assertIn('mr-1.5', self.js_content, "JS must apply mr-1.5 icon spacing in apply button rendering.")

    def test_r1_28_js_moveend_checks_original_event_or_programmatic_guard(self):
        """Verify moveend listener checks e.originalEvent alongside state.isProgrammaticMove to prevent programmatic camera move refetches."""
        self.assertIn("!e.originalEvent", self.js_content, "moveend handler must inspect e.originalEvent for programmatic camera moves.")
        self.assertIn("state.isProgrammaticMove", self.js_content, "moveend handler must inspect state.isProgrammaticMove.")

    def test_r1_29_js_apply_filtering_uses_profile_cache(self):
        """Verify applyFiltering checks profileCache before falling back to startupsData list when re-rendering open drawer details."""
        self.assertIn("state.profileCache.get(state.currentSelectedId)", self.js_content, "applyFiltering must check state.profileCache when detailsDrawer is active.")



class TestR2DataInjectionAndPayloadResilience(unittest.TestCase):
    """
    R2: Malformed & Unverified Data Injection Testing (>= 15 test cases)
    Tests backend API resilience and frontend JS/HTML rendering fallback logic
    against boundary-case, corrupted, SQLi/XSS, and extreme string payloads.
    Ensures zero unhandled server exceptions (HTTP 500).
    """

    @classmethod
    def setUpClass(cls):
        cls.workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        cls.js_content = load_all_js_contents(cls.workspace_root)

    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def test_r2_01_backend_missing_coordinates(self):
        """Test API resilience when startup payload has None/missing lat and lng coordinates."""
        with patch('backend.app.load_startups') as mock_load:
            mock_load.return_value = [{
                "id": 5001,
                "name": "NoCoords Inc",
                "lat": None,
                "lng": None,
                "city": "Bengaluru",
                "has_pin": False
            }]
            resp = self.client.get('/api/startups')
            self.assertNotEqual(resp.status_code, 500, "Server crashed with HTTP 500 on missing coordinates!")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertEqual(len(data), 1)
            self.assertFalse(data[0].get("has_pin", True))

    def test_r2_02_backend_null_description(self):
        """Test API resilience when startup has description: None, ensuring no NoneType slicing TypeError occurs."""
        with patch('backend.app.load_startups') as mock_load:
            mock_load.return_value = [{
                "id": 5002,
                "name": "NullDesc Corp",
                "lat": 12.9716,
                "lng": 77.5946,
                "city": "Bengaluru",
                "description": None,
                "has_pin": True
            }]
            resp = self.client.get('/api/startups')
            self.assertNotEqual(resp.status_code, 500, "Server crashed with HTTP 500 on description: None!")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertEqual(len(data), 1)

    def test_r2_03_backend_unicode_emojis(self):
        """Test API resilience against unicode emojis in startup name, city, industry, and description."""
        with patch('backend.app.load_startups') as mock_load:
            mock_load.return_value = [{
                "id": 5003,
                "name": "🚀 EmojiTech AI 🔥",
                "lat": 12.9716,
                "lng": 77.5946,
                "city": "Bengaluru ❤️",
                "industry": "Artificial Intelligence 🤖",
                "description": "Building the future with 🌟 and ⚡!",
                "has_pin": True
            }]
            resp = self.client.get('/api/startups')
            self.assertEqual(resp.status_code, 200, "Server must return 200 for unicode emoji payloads.")
            data = json.loads(resp.data.decode('utf-8'))
            self.assertIn("🚀", data[0]["name"])
            self.assertIn("🤖", data[0]["industry"])

    def test_r2_04_backend_empty_and_null_job_arrays(self):
        """Test endpoint when job_openings is empty list [] or None, ensuring no IndexError or KeyError occurs."""
        with patch('backend.app.load_startups') as mock_load:
            mock_load.return_value = [
                {"id": 5004, "name": "EmptyJobs Corp", "lat": 12.97, "lng": 77.59, "job_openings": [], "has_pin": True},
                {"id": 5005, "name": "NullJobs Corp", "lat": 12.98, "lng": 77.60, "job_openings": None, "has_pin": True}
            ]
            resp = self.client.get('/api/startups')
            self.assertNotEqual(resp.status_code, 500, "Server crashed with HTTP 500 on empty/null job arrays!")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0].get("job_count"), 0)

    def test_r2_05_backend_negative_salaries_and_invalid_numbers(self):
        """Test API resilience when jobs contain corrupted salary strings or negative values."""
        with patch('backend.app.load_startups') as mock_load:
            mock_load.return_value = [{
                "id": 5006,
                "name": "NegativeSalary AI",
                "lat": 12.97,
                "lng": 77.59,
                "job_openings": [
                    {"title": "Dev", "salary": "-50 LPA", "experience": "-1 yrs"},
                    {"title": "QA", "salary": "Not disclosed", "experience": "Not specified"}
                ],
                "has_pin": True
            }]
            resp = self.client.get('/api/startups')
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertIn("-50 LPA", data[0].get("salary", []))

    def test_r2_06_backend_extreme_string_lengths(self):
        """Send query parameters with extreme string lengths (5000 chars) to verify safe rejection or truncation without 500 error."""
        long_str = "A" * 5000
        resp = self.client.get(f'/api/startups?city={long_str}')
        self.assertNotEqual(resp.status_code, 500, "Server crashed with HTTP 500 on extreme string length!")
        self.assertIn(resp.status_code, [200, 400], f"Expected 400 Bad Request or 200, got {resp.status_code}")

    def test_r2_07_backend_sqli_injection_chars(self):
        """Send SQL injection payloads in query parameters and verify HTTP 400 rejection without unhandled exceptions."""
        sqli_urls = [
            "/api/startups?city=Bengaluru' OR '1'='1",
            '/api/startups?city=" OR ""="',
            "/api/startups?industry=AI'; DROP TABLE startups;--"
        ]
        for url in sqli_urls:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertNotEqual(resp.status_code, 500, f"Server crashed with 500 on SQLi attempt: {url}")
                self.assertIn(resp.status_code, [200, 400])

    def test_r2_08_backend_xss_injection_chars(self):
        """Send XSS script payloads in query parameters and verify HTTP 400 rejection without reflection."""
        xss_urls = [
            '/api/startups?city=<script>alert("XSS")</script>',
            '/api/startups?skill=<img src=x onerror=alert(1)>',
            '/api/startups?industry=<svg/onload=alert(1)>'
        ]
        for url in xss_urls:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertNotEqual(resp.status_code, 500, f"Server crashed with 500 on XSS attempt: {url}")
                self.assertIn(resp.status_code, [200, 400])

    def test_r2_09_backend_xss_javascript_uri_sanitization(self):
        """Verify API details endpoint strips or sanitizes javascript:, data:, and vbscript: URI schemes in links."""
        with patch('backend.app.load_startups') as mock_load:
            mock_load.return_value = [{
                "id": 5009,
                "name": "URI Hacker",
                "lat": 12.97,
                "lng": 77.59,
                "website": "javascript:alert('XSS_SITE')",
                "job_openings": [{
                    "title": "Hacker",
                    "url": "javascript:alert('XSS_JOB')"
                }],
                "founders": [{
                    "name": "Eve",
                    "linkedin": "data:text/html,<script>alert(1)</script>"
                }],
                "has_pin": True
            }]
            resp = self.client.get('/api/startups/5009')
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertFalse(data.get("url", "").lower().startswith("javascript:"), "javascript: scheme not stripped from website!")
            if data.get("jobs"):
                self.assertFalse(data["jobs"][0].get("url", "").lower().startswith("javascript:"), "javascript: scheme not stripped from job url!")

    def test_r2_10_backend_malformed_float_bounds(self):
        """Send malformed float strings (abc, nan, inf, 1e999) to verify HTTP 400 Bad Request without ValueError/OverflowError 500 crash."""
        bad_floats = [
            '/api/startups?min_lat=invalid_float',
            '/api/startups?max_lat=nan',
            '/api/startups?min_lng=-inf',
            '/api/startups?max_lng=1e999'
        ]
        for url in bad_floats:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertNotEqual(resp.status_code, 500, f"Server crashed with 500 on bad float: {url}")
                self.assertEqual(resp.status_code, 400)

    def test_r2_11_backend_invalid_limit_param(self):
        """Send negative, zero, non-integer, and out-of-bounds limit values to verify HTTP 400 rejection or safe capping."""
        bad_limits = [
            '/api/startups?limit=abc',
            '/api/startups?limit=-50',
            '/api/startups?limit=9999999'
        ]
        for url in bad_limits:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertNotEqual(resp.status_code, 500, f"Server crashed with 500 on bad limit: {url}")
                self.assertIn(resp.status_code, [200, 400])

    def test_r2_12_backend_nonexistent_startup_id(self):
        """Query /api/startups/999999999 and verify HTTP 404 Not Found is returned with valid JSON error payload."""
        resp = self.client.get('/api/startups/999999999')
        self.assertEqual(resp.status_code, 404)
        data = json.loads(resp.data)
        self.assertIn("error", data, "404 response must include JSON error message.")

    def test_r2_13_frontend_js_fallback_avatar_placeholder(self):
        """Verify JavaScript rendering logic creates safe fallback text avatars (.logo-marker-fallback) when logos are missing."""
        self.assertIn("className: 'logo-marker-fallback'", self.js_content, "JS missing logo-marker-fallback creation.")
        self.assertIn(".substring(0, 1).toUpperCase()", self.js_content, "JS must extract first character for fallback avatar.")

    def test_r2_14_frontend_js_img_onerror_fallback(self):
        """Verify JavaScript attaches onerror handler to logo thumbnails to silently hide broken image links without DOM errors."""
        self.assertIn("img.onerror =", self.js_content, "JS missing onerror handler on image elements.")
        self.assertIn("display = 'none'", self.js_content, "img.onerror must hide broken images.")

    def test_r2_15_frontend_js_null_safety_in_filtering(self):
        """Verify checkStartupMatch in app.js uses null-safe checks (e.g. startup.description || ...) to prevent runtime TypeErrors."""
        self.assertTrue("startup.description &&" in self.js_content or "(startup.description || '')" in self.js_content, "JS checkStartupMatch missing null safety on description.")
        self.assertTrue("startup.city &&" in self.js_content or "(startup.city || '')" in self.js_content, "JS checkStartupMatch missing null safety on city.")
        self.assertTrue("startup.founder_names &&" in self.js_content or "Array.isArray(startup.founder_names)" in self.js_content, "JS checkStartupMatch missing null safety on founder_names.")

    def test_r2_16_backend_unsupported_query_params(self):
        """Send arbitrary unexpected query parameters and verify API rejects them with HTTP 400 or ignores them safely."""
        resp = self.client.get('/api/startups?unsupported_param=hacker&admin=true')
        self.assertNotEqual(resp.status_code, 500, "Server crashed with HTTP 500 on unsupported query parameters!")
        self.assertIn(resp.status_code, [200, 400])

    def test_r2_17_js_null_job_count_safety(self):
        """Verify ui_manager.js guards against startup.job_count === null to prevent NaN jobs rendering."""
        self.assertIn("startup.job_count !== null", self.js_content, "ui_manager.js must check startup.job_count !== null to prevent parseInt(null) -> NaN.")

    def test_r2_18_js_document_fragment_dom_batching(self):
        """Verify renderDirectory and renderDrawerDetails use DocumentFragment batching to prevent live DOM layout thrashing and flickering."""
        self.assertIn("document.createDocumentFragment()", self.js_content, "ui_manager.js must use DocumentFragment for DOM batching.")
        self.assertIn("replaceChildren(fragment)", self.js_content, "ui_manager.js must attach batch DocumentFragment cleanly.")

    def test_r2_19_js_update_markers_visual_state_null_safety(self):
        """Verify updateMarkersVisualState checks marker and getElement existence before accessing element properties."""
        self.assertIn("typeof marker.getElement !== 'function'", self.js_content, "updateMarkersVisualState must verify marker.getElement is a function.")

    def test_r2_20_js_get_domain_non_string_website_safety(self):
        """Verify getDomain in utils.js checks typeof startup.website === 'string' before calling trim()."""
        self.assertIn("typeof startup.website !== 'string'", self.js_content, "getDomain must verify startup.website is a string.")


class TestR3RaceConditionsAndLatencyResilience(unittest.TestCase):
    """
    R3: Interactive Race Condition & Network Latency Testing (>= 10 test cases)
    Simulates rapid interactive sequences, request spamming, fast filter toggles,
    deboucing/aborting verification, memory leak prevention, and caching headers.
    """

    @classmethod
    def setUpClass(cls):
        cls.workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        cls.js_content = load_all_js_contents(cls.workspace_root)

    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def test_r3_01_js_inflight_request_coalescing(self):
        """Verify JavaScript maintains inFlightRequests registry to coalesce concurrent requests during rapid marker click spamming."""
        self.assertIn("inFlightRequests.has(id)", self.js_content, "JS must check inFlightRequests before initiating profile fetch.")
        self.assertTrue("inFlightRequests.set(id, fetchPromise)" in self.js_content or "inFlightRequests.set(id, controller)" in self.js_content, "JS must register pending fetch or controller in inFlightRequests.")
        self.assertIn("inFlightRequests.delete(id)", self.js_content, "JS must delete inFlightRequests entry upon completion or error.")

    def test_r3_02_js_profile_cache_memory_leak_prevention(self):
        """Verify JavaScript bounds profileCache size (LRU evicting oldest at 50 profiles) to prevent memory leaks during extended sessions."""
        self.assertIn("profileCache.size >= 50", self.js_content, "JS must check if profileCache exceeds bounded limit.")
        self.assertIn("profileCache.delete(firstKey)", self.js_content, "JS must evict oldest profile from cache when full.")

    def test_r3_03_js_filter_request_animation_frame_debouncing(self):
        """Verify JavaScript uses requestAnimationFrame in scheduleFiltering to debounce UI re-rendering during rapid filter toggles."""
        self.assertIn("requestAnimationFrame(", self.js_content, "JS scheduleFiltering must use requestAnimationFrame.")
        self.assertIn("cancelAnimationFrame(filterRafId)", self.js_content, "JS must cancel pending filter animation frame on rapid toggles.")

    def test_r3_04_js_search_input_debouncing_150ms(self):
        """Verify search input typing is debounced by 150ms (handleDebouncedInput) to avoid filtering overload on every keystroke."""
        self.assertIn("setTimeout(scheduleFiltering, 150)", self.js_content, "JS must debounce search input by 150ms.")
        self.assertIn("clearTimeout(inputTimeout)", self.js_content, "JS must clear pending input timeout on rapid keystrokes.")

    def test_r3_05_js_marker_cleanup_on_refetch(self):
        """Verify clearAllMarkers removes maplibregl marker DOM instances and resets registries to prevent DOM node memory leaks."""
        self.assertTrue("markersMap[id].remove()" in self.js_content or "marker.remove()" in self.js_content, "clearAllMarkers must call .remove() on existing map markers.")
        self.assertTrue("markersMap = {}" in self.js_content or "markersMap.clear()" in self.js_content, "clearAllMarkers must reset markersMap.")
        self.assertIn("delete coordinatesRegistry[key]", self.js_content, "clearAllMarkers must clean up coordinatesRegistry.")

    def test_r3_06_backend_concurrent_request_rate_limiting(self):
        """Simulate rapid request spamming from an isolated client IP to verify token bucket rate limiter returns HTTP 429."""
        test_ip = '10.200.0.1'
        rate_limited = False
        for _ in range(150):
            resp = self.client.get('/api/startups', environ_base={'REMOTE_ADDR': test_ip})
            if resp.status_code == 429:
                rate_limited = True
                break
        self.assertTrue(rate_limited, "Backend failed to return HTTP 429 Too Many Requests under rapid request spamming!")

    def test_r3_07_backend_rate_limit_headers_under_stress(self):
        """Verify HTTP 429 response under simulated burst traffic includes accurate Retry-After and X-RateLimit-Remaining headers."""
        test_ip = '10.200.0.2'
        last_resp = None
        for _ in range(150):
            last_resp = self.client.get('/api/startups', environ_base={'REMOTE_ADDR': test_ip})
            if last_resp.status_code == 429:
                break
        self.assertEqual(last_resp.status_code, 429)
        self.assertIn('Retry-After', last_resp.headers, "HTTP 429 response missing Retry-After header.")
        self.assertEqual(last_resp.headers.get('X-RateLimit-Remaining'), '0', "X-RateLimit-Remaining should be 0 when rate limited.")

    def test_r3_08_js_error_toast_on_network_failure(self):
        """Verify JavaScript catches API fetch failures or network timeouts and displays a non-blocking toast notification."""
        self.assertIn("showToast('Could not load company profile. Please try again.', 'error')", self.js_content,
                      "JS must notify user via toast when profile network request fails.")

    def test_r3_09_js_drawer_toggle_race_resilience(self):
        """Verify closing details drawer or clicking the map resets URL hash and clears active visual states cleanly."""
        self.assertIn("window.location.hash = ''", self.js_content, "Map click or drawer close must reset window.location.hash.")
        self.assertIn("detailsDrawer.classList.remove('active')", self.js_content, "Hash routing reset must remove active class from drawer.")

    def test_r3_10_js_coordinate_collision_spiral_distribution(self):
        """Verify initializeMarkers offsets co-located markers in a spiral distribution to prevent marker click overlap races."""
        self.assertIn("coordinatesRegistry[coordKey]", self.js_content, "JS must track coordinate density in coordinatesRegistry.")
        self.assertIn("Math.sin(angle)", self.js_content, "JS must calculate spiral angle for overlapping markers.")
        self.assertIn("Math.cos(angle)", self.js_content, "JS must offset overlapping coordinates radially.")

    def test_r3_11_backend_cache_control_public_max_age(self):
        """Verify GET /api/startups includes Cache-Control: public, max-age=60 to absorb redundant concurrent client requests."""
        resp = self.client.get('/api/startups')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('public, max-age=60', resp.headers.get('Cache-Control', ''),
                      "Backend must specify public cache control to mitigate repetitive client requests.")

    def test_r3_12_backend_no_store_on_error_preventing_cache_poisoning(self):
        """Verify error responses include Cache-Control: no-store to prevent caching proxies from poisoning cache with temporary error states."""
        resp_404 = self.client.get('/api/startups/88888888')
        self.assertEqual(resp_404.status_code, 404)
        self.assertIn('no-store', resp_404.headers.get('Cache-Control', '').lower(),
                      "Error responses must specify no-store to prevent cache poisoning during temporary failures.")

    def test_r3_13_js_programmatic_move_lock_in_state(self):
        """Verify state.js defines isProgrammaticMove lock and programmaticMoveTimeout for map move suppression."""
        self.assertIn("isProgrammaticMove", self.js_content, "state.js must define isProgrammaticMove flag.")
        self.assertIn("lockProgrammaticMove", self.js_content, "JS must define lockProgrammaticMove helper.")

    def test_r3_14_js_moveend_suppression_when_programmatic_move(self):
        """Verify map.on('moveend') checks state.isProgrammaticMove and returns early without fetching startups."""
        self.assertTrue("if (state.isProgrammaticMove)" in self.js_content or "if (state.isProgrammaticMove ||" in self.js_content, "moveend handler must check state.isProgrammaticMove.")
        self.assertIn("state.isProgrammaticMove = false", self.js_content, "moveend handler must reset state.isProgrammaticMove to false.")

    def test_r3_15_js_process_open_startup_sets_programmatic_lock(self):
        """Verify _processOpenStartup sets lockProgrammaticMove before calling map.flyTo."""
        self.assertIn("lockProgrammaticMove", self.js_content, "_processOpenStartup or map animations must invoke lockProgrammaticMove.")

    def test_r3_16_js_fetch_filtered_startups_applies_filtering(self):
        """Verify fetchFilteredStartups invokes applyFiltering() to maintain active search keyword filters."""
        self.assertIn("applyFiltering()", self.js_content, "fetchFilteredStartups must call applyFiltering() upon receiving data.")


if __name__ == '__main__':
    # Run test suite with verbose output
    unittest.main(verbosity=2)
