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
        ("5. Exploratory Combinatorial Cross-Feature E2E", os.path.join(tests_dir, "test_e2e_combinatorial.py"))
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
        print("🏆 [SUCCESS] All 5 automated verification suites (107+ checks) PASSED 100% CLEANLY!")
        print("======================================================================\n")
        sys.exit(0)
    else:
        print("💥 [FAILURE] One or more verification suites failed. Check logs above.")
        print("======================================================================\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
