#!/usr/bin/env python3
"""
Test Suite: tests/test_tokenized_search.py
Verifies backend tokenized search matching logic in filter_and_sort_startups.
"""

import unittest
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.services.startup_service import filter_and_sort_startups

class TestTokenizedSearchMatching(unittest.TestCase):
    def setUp(self):
        self.sample_startups = [
            {
                "id": 1,
                "name": "Greenspace Labs",
                "description": "Eco-friendly smart home systems and IoT devices",
                "city": "Bengaluru",
                "founders": [{"name": "Arjun Mehta"}, {"name": "Sara Ali"}],
                "skills": ["IoT", "Hardware"],
                "job_openings": [
                    {
                        "title": "Embedded Software Engineer",
                        "department": "Engineering",
                        "skills": ["C++", "Python", "RTOS"],
                        "experience": "3+ years",
                        "salary": "INR 18,00,000"
                    }
                ],
                "has_pin": True
            },
            {
                "id": 2,
                "name": "Apex Fintech",
                "description": "Modern algorithmic trading platform and wealth management API",
                "city": "Mumbai",
                "founders": [{"name": "Rohan Shah"}],
                "skills": ["Finance", "Trading"],
                "job_openings": [
                    {
                        "title": "Senior Quantitative Researcher",
                        "department": "Research",
                        "skills": ["Python", "C++", "Pandas"],
                        "experience": "5+ years",
                        "salary": "INR 35,00,000"
                    },
                    {
                        "title": "Backend developer",
                        "department": "Platform",
                        "skills": ["Go", "Docker", "Kubernetes"],
                        "experience": "2+ years",
                        "salary": "INR 15,00,000"
                    }
                ],
                "has_pin": True
            }
        ]

    def test_single_word_match(self):
        # "Fintech" matches Apex Fintech
        res = filter_and_sort_startups(self.sample_startups, None, None, None, None, limit=10, search_query="Fintech")
        ids = [s["id"] for s in res]
        self.assertEqual(ids, [2])

        # "IoT" matches Greenspace Labs
        res = filter_and_sort_startups(self.sample_startups, None, None, None, None, limit=10, search_query="IoT")
        ids = [s["id"] for s in res]
        self.assertEqual(ids, [1])

    def test_multi_word_out_of_order_match(self):
        # query "Engineer Python" matches Greenspace Labs because it has Python in skills and title "Embedded Software Engineer"
        # also matches Apex Fintech because it has Python in researcher skills, but no engineer job title?
        # Wait, Quantitative Researcher has title Quantitative Researcher (no "Engineer"). Let's check:
        # If we query "Engineer Python":
        # - Greenspace Labs: has "Embedded Software Engineer" (matches "engineer"), and "Python" in skills (matches "python"). So matches both.
        # - Apex Fintech: has "Python" in skills, but does it have "Engineer"? Let's check:
        #   It has "Senior Quantitative Researcher" and "Backend developer". Neither title/dept/skills contains "engineer".
        #   So Apex Fintech should NOT match "Engineer Python".
        res = filter_and_sort_startups(self.sample_startups, None, None, None, None, limit=10, search_query="Engineer Python")
        ids = [s["id"] for s in res]
        self.assertEqual(ids, [1])

        # Query "Mumbai trading pandas" should match Apex Fintech (Mumbai city, Trading skill, Pandas job skill)
        res = filter_and_sort_startups(self.sample_startups, None, None, None, None, limit=10, search_query="Mumbai trading pandas")
        ids = [s["id"] for s in res]
        self.assertEqual(ids, [2])

    def test_case_insensitivity(self):
        # Query "gReEnSpAcE" should match Greenspace Labs
        res = filter_and_sort_startups(self.sample_startups, None, None, None, None, limit=10, search_query="gReEnSpAcE")
        ids = [s["id"] for s in res]
        self.assertEqual(ids, [1])

        # Query "ArJuN" should match Greenspace Labs (Arjun Mehta)
        res = filter_and_sort_startups(self.sample_startups, None, None, None, None, limit=10, search_query="ArJuN")
        ids = [s["id"] for s in res]
        self.assertEqual(ids, [1])

    def test_no_matching_tokens(self):
        # Query "React Blockchain" matches neither startup
        res = filter_and_sort_startups(self.sample_startups, None, None, None, None, limit=10, search_query="React Blockchain")
        self.assertEqual(res, [])

        # Query "Python Blockchain" (Python matches both, but Blockchain matches neither)
        res = filter_and_sort_startups(self.sample_startups, None, None, None, None, limit=10, search_query="Python Blockchain")
        self.assertEqual(res, [])

    def test_empty_or_whitespace_query(self):
        # Empty query
        res = filter_and_sort_startups(self.sample_startups, None, None, None, None, limit=10, search_query="")
        self.assertEqual(len(res), 2)

        # Whitespace-only query
        res = filter_and_sort_startups(self.sample_startups, None, None, None, None, limit=10, search_query="   ")
        self.assertEqual(len(res), 2)

if __name__ == "__main__":
    unittest.main(verbosity=2)
