#!/usr/bin/env python3
"""
Master Test Runner: run_tests.py
Executes all automated unit, regression, and E2E verification test suites
located in the permanent `tests/` directory.
"""

import subprocess
import sys
import os

def run_suite(suite_name, script_path):
    print(f"\n======================================================================")
    print(f" [RUNNING SUITE] {suite_name}: {script_path}")
    print(f"======================================================================")
    res = subprocess.run([sys.executable, script_path], cwd=os.path.dirname(__file__), text=True)
    if res.returncode != 0:
        print(f"\n❌ [FAILED] Suite {suite_name} exited with code {res.returncode}")
        return False
    print(f"✅ [PASSED] Suite {suite_name} completed successfully.")
    return True

def main():
    workspace_root = os.path.abspath(os.path.dirname(__file__))
    tests_dir = os.path.join(workspace_root, "tests")
    
    suites = [
        ("1. Direct Modular Unit Tests", os.path.join(tests_dir, "test_unit_modular.py")),
        ("2. Data Pipeline Regression Suite", os.path.join(tests_dir, "test_pipeline_regression.py")),
        ("3. Production Scaling & Security E2E", os.path.join(tests_dir, "test_e2e_production.py")),
        ("4. UI Stress Testing & Bug Remediation E2E", os.path.join(tests_dir, "test_e2e_ui_layout.py")),
        ("5. Exploratory Combinatorial Cross-Feature E2E", os.path.join(tests_dir, "test_e2e_combinatorial.py")),
        ("6. Production Scalability & Bounded Memory Suite", os.path.join(tests_dir, "test_scalability_bounds.py")),
        ("7. Google OAuth & Session Security Verification", os.path.join(tests_dir, "test_oauth_security.py")),
        ("8. E2E Interactive QA (Playwright Chromium)", os.path.join(tests_dir, "test_e2e_interactive_qa.py")),
        ("9. Asynchronous Crawler Queue & Atomic Locking Verification", os.path.join(tests_dir, "test_async_crawler_queue.py")),
        ("10. Client-Side Caching Milestone 2 Backend Verification", os.path.join(tests_dir, "test_backend_m2.py")),
        ("11. Client-Side Caching Milestone 3 Frontend Verification", os.path.join(tests_dir, "test_frontend_m3_caching.py")),
        ("12. Client-Side Caching Milestone 4 Master Verification Suite", os.path.join(tests_dir, "test_client_side_api_caching.py")),
        ("13. Industry Classification Verification", os.path.join(tests_dir, "test_industry_classification.py")),
        ("14. Remote Office Location Verification", os.path.join(tests_dir, "test_remote_office_location.py")),
        ("15. Data Acquisition Pipeline Verification", os.path.join(tests_dir, "test_data_acquisition_pipeline.py")),
        ("16. India Remediation Verification", os.path.join(tests_dir, "test_india_remediation.py")),
        ("17. Database State Tracking & Logo Extraction Unit Tests", os.path.join(tests_dir, "test_database_state_tracking.py")),
        ("18. Remote Office Unpinned Coordinate Retention Verification", os.path.join(tests_dir, "test_remote_unpinned.py")),
        ("19. Cloudflare KV Session Store Integration", os.path.join(tests_dir, "test_oauth_kv.py")),
        ("20. Cloudflare Workers Endpoint Integration", os.path.join(tests_dir, "test_worker_endpoints.py")),
        ("21. E2E Search, Filtering, and Map boundaries Suite", os.path.join(tests_dir, "test_e2e_search_filtering.py")),
        ("22. HTML/JS Syntax & Event Handler Integrity", os.path.join(tests_dir, "test_html_js_parser.py")),
        ("23. Mobile and Web Responsiveness E2E", os.path.join(tests_dir, "test_mobile_responsiveness.py"))
    ]
    
    print("\n⚡ WORLDTECH MAP // FULL-STACK MASTER TEST RUNNER ⚡")
    print(f"Target Directory: {tests_dir}")
    print(f"Total Verification Suites: {len(suites)}\n")
    
    all_passed = True
    for name, path in suites:
        if not os.path.exists(path):
            print(f"❌ [ERROR] Test suite not found: {path}")
            all_passed = False
            break
        success = run_suite(name, path)
        if not success:
            all_passed = False
            break
            
    print(f"\n======================================================================")
    if all_passed:
        print(f"🏆 [SUCCESS] All {len(suites)} automated verification suites PASSED 100% CLEANLY!")
        print("======================================================================\n")
        sys.exit(0)
    else:
        print("💥 [FAILURE] One or more verification suites failed. Check logs above.")
        print("======================================================================\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
