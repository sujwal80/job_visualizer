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
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.abspath(os.path.dirname(__file__)) + os.pathsep + env.get("PYTHONPATH", "")
    res = subprocess.run([sys.executable, script_path], cwd=os.path.dirname(__file__), text=True, env=env)
    if res.returncode != 0:
        print(f"\n❌ [FAILED] Suite {suite_name} exited with code {res.returncode}")
        return False
    print(f"✅ [PASSED] Suite {suite_name} completed successfully.")
    return True

def main():
    workspace_root = os.path.abspath(os.path.dirname(__file__))
    tests_dir = os.path.join(workspace_root, "tests")
    
    suites = [
        ("1. Data Pipeline Regression Suite", os.path.join(tests_dir, "test_pipeline_regression.py")),
        ("2. Data Acquisition Pipeline Verification", os.path.join(tests_dir, "test_data_acquisition_pipeline.py")),
        ("3. India Remediation Verification", os.path.join(tests_dir, "test_india_remediation.py")),
        ("4. Revalidation & Healing Engine AC Unit Verification Suite", os.path.join(tests_dir, "test_revalidation_healing_engine.py")),
        ("5. Asynchronous Crawler Queue & Atomic Locking Verification", os.path.join(tests_dir, "test_async_crawler_queue.py")),
        ("6. Industry Classification Verification", os.path.join(tests_dir, "test_industry_classification.py")),
        ("7. Remote Office Location Verification", os.path.join(tests_dir, "test_remote_office_location.py")),
        ("8. Database State Tracking & Logo Extraction Unit Tests", os.path.join(tests_dir, "test_database_state_tracking.py")),
        ("9. Caching Optimizations Unit Verification", os.path.join(tests_dir, "test_caching_optimizations_unit.py")),
        ("10. Crawler Unit Verification", os.path.join(tests_dir, "test_crawler_unit.py")),
        ("11. Logo and Domain Refactor Verification", os.path.join(tests_dir, "test_logo_and_domain_refactor.py")),
        ("12. R3 Deduplication Slugs Verification", os.path.join(tests_dir, "test_r3_deduplication_slugs.py")),
        ("13. Request Deduplication Cache Verification", os.path.join(tests_dir, "test_request_deduplication_cache.py")),
        ("14. HTML/JS Syntax & Event Handler Integrity", os.path.join(tests_dir, "test_html_js_parser.py")),
        ("15. Online Revalidation E2E Verification Suite", os.path.join(tests_dir, "test_online_revalidation_e2e.py")),
        ("16. Adversarial Revalidation Hardening Suite", os.path.join(tests_dir, "test_adversarial_revalidation.py")),
        ("17. Revalidate Hourly Service Verification Suite", os.path.join(tests_dir, "test_revalidate_hourly_service.py")),
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
