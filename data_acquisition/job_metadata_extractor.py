"""
Job Metadata Extractor Module

Centralized extractor using zero-dependency regex and API dictionary parsing
to extract standardized inline metadata from job titles, raw snippets, and extra API data.
"""

import re
from typing import Dict, List, Optional, Any


SKILL_PATTERNS = [
    ("Python", r'\bPython\b'),
    ("React Native", r'\bReact\s*Native\b'),
    ("React", r'\bReact(?:js|\.js)?\b(?!\s*Native)'),
    ("Node", r'\bNode(?:js|\.js)?\b'),
    ("Next.js", r'\bNext(?:js|\.js)\b'),
    ("Vue", r'\bVue(?:js|\.js)?\b'),
    ("Angular", r'\bAngular(?:js)?\b'),
    ("JavaScript", r'\b(?:JavaScript|JS)\b'),
    ("TypeScript", r'\b(?:TypeScript|TS)\b'),
    ("Java", r'\bJava\b(?!\s*Script)'),
    ("C++", r'\bC\+\+(?!\w)'),
    ("C#", r'\bC#(?!\w)'),
    ("Go", r'\b(?:Golang)\b|\bGo\b(?=\s*(?:Developer|Engineer|Programming|Lang|Stack|\,|\.|\)|$))'),
    ("Rust", r'\bRust\b'),
    ("Ruby on Rails", r'\b(?:Ruby\s*on\s*Rails|RoR)\b'),
    ("Ruby", r'\bRuby\b(?!\s*on\s*Rails)'),
    ("PHP", r'\bPHP\b'),
    ("Swift", r'\bSwift\b'),
    ("Kotlin", r'\bKotlin\b'),
    ("Scala", r'\bScala\b'),
    ("HTML", r'\bHTML5?\b'),
    ("CSS", r'\bCSS3?\b'),
    ("SQL", r'\bSQL\b'),
    ("NoSQL", r'\bNoSQL\b'),
    ("Django", r'\bDjango\b'),
    ("Flask", r'\bFlask\b'),
    ("FastAPI", r'\bFastAPI\b'),
    ("Spring Boot", r'\bSpring\s*Boot\b'),
    ("Spring", r'\bSpring\b(?!\s*Boot)'),
    ("Express", r'\bExpress(?:js|\.js)?\b'),
    ("PyTorch", r'\bPyTorch\b'),
    ("TensorFlow", r'\bTensorFlow\b'),
    ("Pandas", r'\bPandas\b'),
    ("NumPy", r'\bNumPy\b'),
    ("AWS", r'\b(?:AWS|Amazon\s*Web\s*Services)\b'),
    ("GCP", r'\b(?:GCP|Google\s*Cloud|Google\s*Cloud\s*Platform)\b'),
    ("Azure", r'\bAzure\b'),
    ("Docker", r'\bDocker\b'),
    ("Kubernetes", r'\b(?:Kubernetes|K8s)\b'),
    ("Terraform", r'\bTerraform\b'),
    ("PostgreSQL", r'\b(?:PostgreSQL|Postgres)\b'),
    ("MongoDB", r'\bMongoDB\b'),
    ("MySQL", r'\bMySQL\b'),
    ("Redis", r'\bRedis\b'),
    ("Elasticsearch", r'\bElasticsearch\b'),
    ("Kafka", r'\bKafka\b'),
    ("GraphQL", r'\bGraphQL\b'),
    ("REST API", r'\bREST(?:ful)?\s*APIs?\b'),
    ("Git", r'\bGit\b(?!\s*Hub|\s*Lab)'),
    ("Linux", r'\bLinux\b'),
    ("CI/CD", r'\bCI/CD\b'),
]


def _clean_text(text: Any) -> str:
    if not text:
        return ""
    return re.sub(r'\s+', ' ', str(text)).strip()


def _extract_experience(title: str, snippet: str, extra_data: Dict[str, Any]) -> str:
    # 1. Check extra_data first
    for key in ("experience", "work_experience", "exp", "experience_range"):
        val = extra_data.get(key)
        if val and isinstance(val, str) and val.strip():
            return _clean_text(val)
        elif val and isinstance(val, dict):
            min_exp = val.get("min") if val.get("min") is not None else val.get("minimum")
            max_exp = val.get("max") if val.get("max") is not None else val.get("maximum")
            if min_exp is not None and max_exp is not None:
                return f"{min_exp}-{max_exp} yrs"
            elif min_exp is not None:
                return f"{min_exp}+ yrs"

    min_exp = extra_data.get("min_experience") if "min_experience" in extra_data else extra_data.get("min_exp")
    max_exp = extra_data.get("max_experience") if "max_experience" in extra_data else extra_data.get("max_exp")
    if min_exp is not None and max_exp is not None:
        return f"{min_exp}-{max_exp} yrs"
    elif min_exp is not None:
        return f"{min_exp}+ yrs"

    # 2. Check title then snippet with regex
    for text in (title, snippet):
        if not text:
            continue
        # Range e.g. 3-5 yrs, 3 - 5 years, 3 to 5 YOE
        range_match = re.search(r'(\d+)\s*(?:-|–|—|to)\s*(\d+)\s*\+?\s*(?:yrs?|years?|yoe|Yrs?|Years?|YOE)\b', text, re.IGNORECASE)
        if range_match:
            return f"{range_match.group(1)}-{range_match.group(2)} yrs"

        # Plus e.g. 3+ yrs, 5+ years
        plus_match = re.search(r'(\d+)\s*\+\s*(?:yrs?|years?|yoe|Yrs?|Years?|YOE)\b', text, re.IGNORECASE)
        if plus_match:
            return f"{plus_match.group(1)}+ yrs"

        # Exact e.g. 3 yrs, 2 years
        exact_match = re.search(r'(\d+)\s*(?:yrs?|years?|yoe|Yrs?|Years?|YOE)\b', text, re.IGNORECASE)
        if exact_match:
            return f"{exact_match.group(1)} yrs"

        # Fresher / Entry Level
        if re.search(r'\b(?:Fresher|Freshers|Entry\s*Level|Fresh\s*Graduate)\b', text, re.IGNORECASE):
            return "Fresher"

    return "Not specified"


def _extract_salary(title: str, snippet: str, extra_data: Dict[str, Any]) -> str:
    # 1. Check extra_data first
    for key in ("salary", "compensation", "pay", "ctc", "salary_range"):
        val = extra_data.get(key)
        if val and isinstance(val, str) and val.strip():
            return _clean_text(val)
        elif val and isinstance(val, dict):
            min_sal = val.get("min") if val.get("min") is not None else val.get("minimum")
            max_sal = val.get("max") if val.get("max") is not None else val.get("maximum")
            curr = val.get("currency", "₹")
            unit = val.get("unit", "LPA")
            if min_sal is not None and max_sal is not None:
                return f"{curr}{min_sal} - {curr}{max_sal} {unit}"

    # 2. Check title then snippet with regex
    for text in (title, snippet):
        if not text:
            continue
        # Pattern 1: Range with currency or LPA/PA/Lakhs/Cr/K
        pat1 = r'((?:₹|INR|\$|USD|EUR|£)\s*[\d,]+(?:\.\d+)?\s*(?:L|Lakh|Lakhs|LPA|K|k|Cr|cr|m|M)?\s*(?:-|–|—|to)\s*(?:₹|INR|\$|USD|EUR|£)?\s*[\d,]+(?:\.\d+)?\s*(?:L|Lakh|Lakhs|LPA|K|k|Cr|cr|m|M)?\s*(?:LPA|lpa|PA|pa|per\s*annum)?)'
        match1 = re.search(pat1, text)
        if match1:
            return _clean_text(match1.group(1))

        # Pattern 2: Range without leading currency symbol, but ending with LPA/PA/Lakhs
        pat2 = r'([\d,]+(?:\.\d+)?\s*(?:L|Lakh|Lakhs|K|k|Cr|cr)?\s*(?:-|–|—|to)\s*(?:₹|INR|\$|USD|EUR|£)?\s*[\d,]+(?:\.\d+)?\s*(?:L|Lakh|Lakhs|LPA|K|k|Cr|cr)?\s*(?:LPA|lpa|PA|pa|per\s*annum))'
        match2 = re.search(pat2, text, re.IGNORECASE)
        if match2:
            return _clean_text(match2.group(1))

        # Pattern 3: Single salary amount with currency symbol or LPA
        pat3 = r'((?:₹|INR|\$|USD|EUR|£)\s*[\d,]+(?:\.\d+)?\s*(?:L|Lakh|Lakhs|LPA|K|k|Cr|cr|m|M)\s*(?:LPA|lpa|PA|pa)?)'
        match3 = re.search(pat3, text)
        if match3:
            return _clean_text(match3.group(1))

        pat4 = r'([\d,]+(?:\.\d+)?\s*(?:L|Lakh|Lakhs|Cr|cr)\s*(?:LPA|lpa|PA|pa))'
        match4 = re.search(pat4, text, re.IGNORECASE)
        if match4:
            return _clean_text(match4.group(1))

    return "Not specified"


def _extract_job_type(title: str, snippet: str, extra_data: Dict[str, Any]) -> str:
    # 1. Check extra_data first
    for key in ("job_type", "employment_type", "type", "schedule"):
        val = extra_data.get(key)
        if val and isinstance(val, str) and val.strip():
            val_lower = val.lower()
            if "intern" in val_lower:
                return "Internship"
            elif "contract" in val_lower or "freelance" in val_lower:
                return "Contract"
            elif "part" in val_lower:
                return "Part-time"
            elif "full" in val_lower or "permanent" in val_lower:
                return "Full-time"
            return _clean_text(val).title()

    # 2. Check title then snippet with regex
    for text in (title, snippet):
        if not text:
            continue
        if re.search(r'\b(?:Internship|Intern|Interns)\b', text, re.IGNORECASE):
            return "Internship"
        if re.search(r'\b(?:Contract|Contractor|Freelance)\b', text, re.IGNORECASE):
            return "Contract"
        if re.search(r'\b(?:Part-time|Parttime|Part\s*Time)\b', text, re.IGNORECASE):
            return "Part-time"
        if re.search(r'\b(?:Full-time|Fulltime|Full\s*Time|Permanent)\b', text, re.IGNORECASE):
            return "Full-time"

    return "Not specified"


def _extract_skills(title: str, snippet: str, extra_data: Dict[str, Any]) -> List[str]:
    extracted_skills: List[str] = []
    seen = set()

    def add_skill(skill: str):
        if skill and skill.lower() not in seen:
            seen.add(skill.lower())
            extracted_skills.append(skill)

    # 1. Check extra_data first
    for key in ("skills", "tags", "required_skills", "technologies", "tech_stack"):
        val = extra_data.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.strip():
                    add_skill(_clean_text(item))
        elif isinstance(val, str) and val.strip():
            for item in re.split(r'[,;\|]', val):
                if item.strip():
                    add_skill(_clean_text(item))

    # 2. Regex match on combined text
    combined = f"{title} {snippet}"
    for canonical_name, pattern in SKILL_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            add_skill(canonical_name)

    return extracted_skills


def _extract_posted_date(title: str, snippet: str, extra_data: Dict[str, Any]) -> str:
    # 1. Check extra_data first
    for key in ("posted_date", "date_posted", "created_at", "published_at", "freshness", "posted"):
        val = extra_data.get(key)
        if val and isinstance(val, str) and val.strip():
            return _clean_text(val)

    # 2. Check title then snippet with regex
    for text in (title, snippet):
        if not text:
            continue
        match = re.search(r'\b(?:Posted\s*)?(\d+\+?\s*(?:days?|d|weeks?|w|months?|m|hours?|h)\s*ago|Just\s*now|Today|Yesterday|Active\s*\d+\s*(?:days?|d)\s*ago)\b', text, re.IGNORECASE)
        if match:
            return _clean_text(match.group(0))

    return "Recent"


def extract_job_metadata(title: str, raw_snippet: str = "", extra_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Extract standardized job metadata (experience, salary, job_type, skills, posted_date)
    from title, raw_snippet, and optional extra API data.
    """
    if title is None:
        title = ""
    if raw_snippet is None:
        raw_snippet = ""
    if extra_data is None or not isinstance(extra_data, dict):
        extra_data = {}

    experience = _extract_experience(title, raw_snippet, extra_data)
    salary = _extract_salary(title, raw_snippet, extra_data)
    job_type = _extract_job_type(title, raw_snippet, extra_data)
    skills = _extract_skills(title, raw_snippet, extra_data)
    posted_date = _extract_posted_date(title, raw_snippet, extra_data)

    return {
        "experience": experience,
        "salary": salary,
        "job_type": job_type,
        "skills": skills,
        "posted_date": posted_date,
    }
