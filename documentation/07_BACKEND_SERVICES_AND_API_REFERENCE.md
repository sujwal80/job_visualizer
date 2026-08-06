# Backend Services & API Reference

> Exhaustive API documentation, endpoint specifications, request/response schemas, authentication protocols, rate limiting, and security controls.

---

## 1. Backend Architecture & Runtime

The backend runs as a **Cloudflare Edge Worker** in a V8 JavaScript runtime (`compatibility_date = "2024-09-19"`, `compatibility_flags = ["nodejs_compat"]`). It provides sub-millisecond routing and serverless scalability.

```text
Incoming HTTP Request
   │
   ▼
[backend/worker.js]
   │
   ├─► Asset Request? (/static/*, /index.html) ──► Serve from env.ASSETS
   │
   └─► API Request? (/api/*) ──► [backend/unified_router.js]
                                       │
                        ┌──────────────┴──────────────┐
                        ▼                             ▼
              [startup_service.js]           [auth_service.js]
              (Search & Filtering)           (OAuth2 & Sessions)
```

---

## 2. API Endpoints Reference

### 2.1 Startups & Job Discovery

#### `GET /api/startups`
Searches, filters, and returns startup summaries and job openings.

* **Query Parameters**:
  | Parameter | Type | Required | Description |
  | :--- | :--- | :--- | :--- |
  | `min_lat` | `float` | Optional | Southern latitude boundary of viewport. |
  | `max_lat` | `float` | Optional | Northern latitude boundary of viewport. |
  | `min_lng` | `float` | Optional | Western longitude boundary of viewport. |
  | `max_lng` | `float` | Optional | Eastern longitude boundary of viewport. |
  | `city` | `string` | Optional | Canonical city filter (e.g. `"Bengaluru"`, `"Mumbai"`). |
  | `q` | `string` | Optional | Tokenized search query (matches name, description, address, skills, jobs). |
  | `industry`| `string` | Optional | Sector filter (e.g. `"Artificial Intelligence"`, `"Fintech"`). |
  | `role` | `string` | Optional | Job title / keyword filter (e.g. `"Backend Engineer"`). |
  | `salary_min`| `float` | Optional | Minimum salary in LPA (Lakhs per Annum). |
  | `exp_level` | `string` | Optional | Experience level (`"entry"`, `"mid"`, `"senior"`, or numeric years). |
  | `work_type` | `string` | Optional | Work arrangement (`"remote"`, `"hybrid"`, `"on-site"`). |
  | `limit` | `int` | Optional | Max items returned (default: `100`). |

* **Response (`200 OK`)**:
  ```json
  [
    {
      "id": 1,
      "name": "Hasura",
      "lat": 12.9716,
      "lng": 77.5946,
      "city": "Bengaluru",
      "industry": "SaaS",
      "logo_url": "https://hasura.io/brand-assets/hasura-logo-primary.svg",
      "website": "https://hasura.io",
      "funding_stage": "Series C",
      "total_raised": "$136.5M",
      "job_count": 4,
      "job_titles": [
        "Senior Backend Engineer (Go / Rust)",
        "Staff Developer Advocate",
        "Frontend Engineer (React)"
      ],
      "skills": ["GraphQL", "Go", "PostgreSQL", "React", "Rust"],
      "offices": [
        {
          "city": "Bengaluru",
          "office_address": "Indiqube Coral, 4th Floor, 80 Feet Rd, Koramangala, Bengaluru, Karnataka 560034",
          "lat": 12.9345,
          "lng": 77.6254,
          "is_hq": true
        }
      ]
    }
  ]
  ```

---

#### `GET /api/startups/:id`
Retrieves full details for a single company entity.

* **URL Parameters**: `id` (`integer`, required)
* **Response (`200 OK`)**:
  ```json
  {
    "id": 1,
    "name": "Hasura",
    "city": "Bengaluru",
    "description": "Hasura makes your data instantly accessible over a real-time GraphQL or REST API.",
    "industry": "SaaS",
    "funding_stage": "Series C",
    "total_raised": "$136.5M",
    "website": "https://hasura.io",
    "logo_url": "https://hasura.io/brand-assets/hasura-logo-primary.svg",
    "founders": [
      {
        "name": "Tanmai Gopal",
        "linkedin": "https://www.linkedin.com/in/tanmaigopal"
      }
    ],
    "jobs": [
      {
        "title": "Senior Backend Engineer",
        "department": "Engineering",
        "salary": "₹35L - ₹50L",
        "experience": "5+ years",
        "job_type": "Full-time",
        "location": "Bengaluru (Hybrid)",
        "skills": ["Go", "Haskell", "Distributed Systems"],
        "url": "https://hasura.io/careers/senior-backend-engineer",
        "source": "Direct"
      }
    ],
    "offices": [
      {
        "city": "Bengaluru",
        "office_address": "Indiqube Coral, 4th Floor, 80 Feet Rd, Koramangala, Bengaluru, Karnataka 560034",
        "lat": 12.9345,
        "lng": 77.6254,
        "is_hq": true
      }
    ]
  }
  ```

---

### 2.2 Authentication & User Profiles

#### `GET /api/auth/google`
Generates Google OAuth2 authorization URL with PKCE security parameters and redirects the user.

#### `GET /api/auth/callback`
Receives Google OAuth code, exchanges it for profile tokens, upserts user in Cloudflare D1, and sets a signed `auth_token` JWT cookie.

#### `GET /api/auth/me`
Returns current authenticated session user profile or `401 Unauthorized`.

#### `POST /api/auth/logout`
Invalidates session and clears the `auth_token` cookie.

---

### 2.3 User Bookmarks (D1 Relational Store)

#### `GET /api/bookmarks`
Returns array of startup and job IDs bookmarked by the authenticated user.

#### `POST /api/bookmarks`
* **Body**: `{"startup_id": 142, "job_title": "Frontend Engineer"}`
* **Response**: `{"status": "saved"}`

---

### 2.4 System Health & Metadata

#### `GET /api/health`
* **Response (`200 OK`)**:
  ```json
  {
    "status": "healthy",
    "environment": "production",
    "version": "1.0.0",
    "timestamp": 1786018487
  }
  ```

---

## 3. Security, Rate Limiting & Validation

1. **Input Sanitization (`backend/utils/validators.js`)**:
   - Strips malicious control characters and HTML tags.
   - Restricts latitude values to `[-90.0, 90.0]` and longitude to `[-180.0, 180.0]`.
   - Validates URLs against protocol whitelists (`http://`, `https://`).
2. **Rate Limiter (`backend/utils/rate_limiter.js`)**:
   - Sliding window limiter tracks request frequency per client IP.
   - Threshold: **60 requests per minute** for unauthenticated users; authenticated requests receive higher burst allowances.
3. **JWT Verification (`backend/utils/jwt_helper.js`)**:
   - HMAC-SHA256 signing using high-entropy production secret.
   - Embedded expiry check (`exp`) and token revocation list checks via Cloudflare KV.
