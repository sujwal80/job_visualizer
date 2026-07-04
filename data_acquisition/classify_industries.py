#!/usr/bin/env python3
"""
Standalone Industry Classification Script

Analyzes startup records in backend/startups.json and assigns accurate startup sectors:
Artificial Intelligence, Fintech, SaaS, E-commerce, HealthTech, EdTech, CleanTech, Cybersecurity, Logistics, B2B.
"""

import json
import os
import re

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'backend', 'startups.json')

TAXONOMY = [
    ("Artificial Intelligence", r'\b(?:ai|artificial\s*intelligence|machine\s*learning|llm|genai|generative\s*ai|nlp|deep\s*learning|computer\s*vision)\b'),
    ("Fintech", r'\b(?:fintech|payment|payments|banking|credit|lending|insurance|insurtech|wealth|crypto|blockchain|finance|neobank|accounting)\b'),
    ("HealthTech", r'\b(?:health|healthtech|biotech|medical|pharma|clinical|healthcare|wellness|genomics)\b'),
    ("E-commerce", r'\b(?:e-commerce|ecommerce|marketplace|d2c|retail|shopping|q-commerce|quick\s*commerce)\b'),
    ("EdTech", r'\b(?:edtech|education|learning|upskilling|tutor|university|course)\b'),
    ("CleanTech", r'\b(?:cleantech|climate|solar|ev|electric\s*vehicle|battery|renewable|sustainability|carbon)\b'),
    ("Cybersecurity", r'\b(?:security|cybersecurity|infosec|encryption|identity|firewall|compliance)\b'),
    ("Logistics", r'\b(?:logistics|supply\s*chain|fleet|mobility|freight|delivery|warehousing)\b'),
    ("SaaS", r'\b(?:saas|b2b|enterprise|cloud|workflow|api|platform|devtool|software)\b')
]

def classify_startup(startup):
    curr = str(startup.get("industry") or "").strip()
    valid_sectors = {t[0] for t in TAXONOMY}
    if curr in valid_sectors and curr != "SaaS":
        return curr

    text = f"{startup.get('name', '')} {startup.get('description', '')} {startup.get('website', '')}".lower()
    for j in startup.get("job_openings", []):
        if isinstance(j, dict):
            text += f" {j.get('title', '')} {j.get('department', '')}".lower()

    for sector, pattern in TAXONOMY:
        if re.search(pattern, text, re.IGNORECASE):
            return sector

    return curr if curr and curr not in ["N/A", "Software", "Software Development", "Information Technology"] else "SaaS"

def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    with open(DB_PATH, 'r') as f:
        data = json.load(f)

    updated_count = 0
    for s in data:
        old_ind = s.get("industry")
        new_ind = classify_startup(s)
        if old_ind != new_ind:
            s["industry"] = new_ind
            updated_count += 1

    with open(DB_PATH, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"Successfully processed {len(data)} startups. Updated industry classifications for {updated_count} startups.")

if __name__ == '__main__':
    main()
