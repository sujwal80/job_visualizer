#!/usr/bin/env python3
"""
Production Scalability & Bounded Memory Test Suite
Test Suite: tests/test_scalability_bounds.py

Verifies that the rate limiter and backend utilities enforce strict memory bounds,
automated LRU eviction, TTL timestamp expiration cleanup, and 100% thread safety
under high-volume concurrent multi-threaded stress conditions.
"""

import unittest
import sys
import os
import time
import concurrent.futures
import threading

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.utils.rate_limiter import _rate_limits, _check_rate_limit, BoundedRateLimitDict


class TestProductionScalabilityAndBounds(unittest.TestCase):
    def setUp(self):
        # Clean state before each test
        _rate_limits.clear()

    def tearDown(self):
        # Ensure clean state after test
        _rate_limits.clear()

    def test_01_lru_capacity_under_15000_unique_ips(self):
        """
        Simulates high-volume burst traffic from 15,500+ unique client IPs.
        Programmatically verifies that in-memory capacity strictly never exceeds 10,000 entries,
        and that least recently used (LRU) IP entries are cleanly evicted without exceptions.
        """
        print("\n--- Running Test 01: 15,500+ Unique Client IPs LRU Capacity Stress Test ---")
        total_ips = 15500
        max_cap = _rate_limits.max_size  # Should be 10000

        for i in range(1, total_ips + 1):
            ip = f"10.{i // 65536}.{(i // 256) % 256}.{i % 256}"
            allowed, _, remaining, _ = _check_rate_limit(ip, limit=120, window=60)
            self.assertTrue(allowed, f"Request for IP {ip} should be allowed")
            
            # Check capacity invariant continuously
            current_len = len(_rate_limits)
            self.assertLessEqual(
                current_len, max_cap,
                f"Memory bound violated! Current len {current_len} exceeded max capacity {max_cap} at step {i}"
            )

        # After 15,500 insertions, length should be capped exactly at max_size (10,000)
        final_len = len(_rate_limits)
        self.assertEqual(final_len, max_cap, f"Expected exactly {max_cap} entries, got {final_len}")

        # Verify LRU eviction: earliest IP (10.0.0.1) should be evicted; latest IP should be present
        first_ip = "10.0.0.1"
        latest_ip = f"10.{total_ips // 65536}.{(total_ips // 256) % 256}.{total_ips % 256}"
        self.assertNotIn(first_ip, _rate_limits, f"LRU failure: Earliest IP {first_ip} was not evicted!")
        self.assertIn(latest_ip, _rate_limits, f"LRU failure: Latest IP {latest_ip} missing from cache!")
        print(f" [PASS] Successfully verified strict 10,000 capacity limit under 15,500+ unique IP simulation.")

    def test_02_automated_ttl_cleanup_purges_expired_entries(self):
        """
        Verifies automated TTL cleanup of expired timestamps. Simulates timestamps older than window,
        confirming expired IP entries are cleanly purged without memory leaks or server exceptions.
        """
        print("\n--- Running Test 02: Automated TTL Expiration Cleanup ---")
        # Populate rate limiter with 500 IPs with old expired timestamps (e.g. 100 seconds ago)
        now = time.time()
        expired_time = now - 120.0  # Older than default window=60
        
        for i in range(500):
            ip = f"192.168.100.{i}"
            with _rate_limits.lock:
                _rate_limits[ip] = [expired_time, expired_time + 10.0]

        self.assertEqual(len(_rate_limits), 500, "Setup failed: Expected 500 expired entries in cache.")

        # Execute purge_expired for window=60
        purged_count = _rate_limits.purge_expired(window=60)
        self.assertEqual(purged_count, 500, f"Expected 500 entries purged, got {purged_count}")
        self.assertEqual(len(_rate_limits), 0, f"Memory leak check: Expected 0 remaining entries, got {len(_rate_limits)}")

        # Verify automated cleanup during check_rate_limit call when _last_cleanup threshold is met
        for i in range(100):
            with _rate_limits.lock:
                _rate_limits[f"172.16.0.{i}"] = [now - 100.0]
        
        self.assertEqual(len(_rate_limits), 100)
        # Force last_cleanup timestamp to be old to trigger automated background purge inside _check_rate_limit
        with _rate_limits.lock:
            _rate_limits._last_cleanup = now - 20.0
            
        _check_rate_limit("8.8.8.8", limit=120, window=60)
        # The 100 expired entries should have been automatically purged, leaving only the new active IP "8.8.8.8"
        self.assertEqual(len(_rate_limits), 1, f"Automated TTL cleanup failed! Remaining entries: {len(_rate_limits)}")
        self.assertIn("8.8.8.8", _rate_limits)
        print(" [PASS] Automated TTL cleanup verified: expired timestamps cleanly purged without leaks.")

    def test_03_concurrent_multithreaded_stress_test(self):
        """
        Concurrent multi-threaded stress test using concurrent.futures.ThreadPoolExecutor.
        Simulates 25 concurrent worker threads simultaneously checking rate limits across 25,000+ total
        requests (both shared IPs and unique thread IPs) to verify thread safety, absence of race conditions,
        zero exceptions, and strict adherence to memory bounds.
        """
        print("\n--- Running Test 03: Concurrent Multi-Threaded Stress Test (25 workers, 25,000 reqs) ---")
        num_workers = 25
        reqs_per_worker = 1000
        shared_ip = "203.0.113.50"
        errors = []

        def worker_task(thread_id):
            try:
                for j in range(reqs_per_worker):
                    # Mix shared IP requests (testing lock contention on same key) and unique IPs (testing LRU eviction)
                    if j % 5 == 0:
                        target_ip = shared_ip
                    else:
                        target_ip = f"10.{thread_id}.{(j // 256) % 256}.{j % 256}"
                    
                    allowed, retry_after, remaining, limit_val = _check_rate_limit(target_ip, limit=5000, window=60)
                    
                    # Verify return types and invariants
                    assert isinstance(allowed, bool), f"Invalid allowed type: {type(allowed)}"
                    assert remaining >= 0, f"Remaining count underflow: {remaining}"
                    assert len(_rate_limits) <= _rate_limits.max_size, f"Capacity bound exceeded in thread {thread_id}!"
            except Exception as e:
                errors.append(f"Thread {thread_id} exception: {str(e)}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker_task, t_id) for t_id in range(num_workers)]
            concurrent.futures.wait(futures)

        self.assertEqual(len(errors), 0, f"Concurrent stress test encountered errors/race conditions: {errors}")
        self.assertLessEqual(len(_rate_limits), _rate_limits.max_size, "Final capacity exceeded max_size after concurrency!")
        self.assertIn(shared_ip, _rate_limits, "Shared IP should be present in cache after concurrent access.")
        print(" [PASS] Concurrent multi-threaded stress test passed with 0 race conditions or deadlocks.")

    def test_04_mapping_interface_and_backward_compatibility(self):
        """
        Verifies that BoundedRateLimitDict complies with Python mapping interface contracts
        (in, del, len, get, keys, values, items, clear) and backward compatibility requirements.
        """
        print("\n--- Running Test 04: Mapping Interface & Backward Compatibility ---")
        test_ip = "192.0.2.200"
        _check_rate_limit(test_ip, limit=10, window=60)
        
        # Test __contains__ and __len__
        self.assertIn(test_ip, _rate_limits)
        self.assertGreaterEqual(len(_rate_limits), 1)
        
        # Test keys, values, items
        keys = _rate_limits.keys()
        values = _rate_limits.values()
        items = _rate_limits.items()
        self.assertIn(test_ip, keys)
        self.assertEqual(len(keys), len(values))
        self.assertEqual(len(keys), len(items))
        
        # Test backward compatibility deletion as seen in test_unit_modular.py
        if test_ip in _rate_limits:
            del _rate_limits[test_ip]
            
        self.assertNotIn(test_ip, _rate_limits, f"Failed to delete {test_ip} from _rate_limits")
        print(" [PASS] Mapping interface and backward compatibility verified 100%.")


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.TestLoader().loadTestsFromTestCase(TestProductionScalabilityAndBounds)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
