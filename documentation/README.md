# MapMyJob / Startup Visualizer — System Documentation

> Comprehensive architecture, data acquisition pipeline, geocoding engine, logo enrichment, frontend UX, backend services, testing strategy, deployment guides, and experimental history for **MapMyJob (Job & Startup Visualizer)**.

---

## 📚 Documentation Index

| File | Document | Description |
| :--- | :--- | :--- |
| **[01_SYSTEM_ARCHITECTURE.md](./01_SYSTEM_ARCHITECTURE.md)** | **System Architecture & Data Flow** | Edge computing model (Cloudflare Workers), Cloudflare D1 SQLite & KV namespaces, Single Page Application frontend, and asynchronous Python data pipelines. |
| **[02_DATA_ACQUISITION_PIPELINE.md](./02_DATA_ACQUISITION_PIPELINE.md)** | **Data Acquisition & Crawling Pipeline** | Multi-source scrapers (LinkedIn, Wellfound/AngelList, Instahyre, company career portals), crawl queues, job validation, and ingestion engines. |
| **[03_OFFICE_ADDRESS_AND_GEOCODING.md](./03_OFFICE_ADDRESS_AND_GEOCODING.md)** | **Office Address Cleaning & Geocoding** | History of what we tried, address normalization rules, multi-stage fallback (Google Maps API, Esri ArcGIS, Photon, Gazetteer), quota tracking, and coordinate resolution. |
| **[04_LOCALITY_SEARCH_AND_MAP_ZOOM.md](./04_LOCALITY_SEARCH_AND_MAP_ZOOM.md)** | **Locality Search & Dynamic Map Zoom** | Sub-city address tokenization ("Koramangala", "BKC", "Cyber City", "Gachibowli"), dynamic bounding box calculation, marker clustering, and smart viewport zoom clamps. |
| **[05_LOGO_EXTRACTION_AND_ENRICHMENT.md](./05_LOGO_EXTRACTION_AND_ENRICHMENT.md)** | **Logo Extraction & Quality Scoring** | Headless Chrome CDP DOM scraping, vector SVG extraction, 100-point scoring algorithm, domain blacklisting, and fallback avatar hierarchy. |
| **[06_DATA_DEDUPLICATION_AND_HEALING.md](./06_DATA_DEDUPLICATION_AND_HEALING.md)** | **Data Deduplication & Automated Healing** | Entity resolution algorithms, canonical slug generation, hourly revalidation engines, dead job pruning, and data integrity audits. |
| **[07_BACKEND_SERVICES_AND_API_REFERENCE.md](./07_BACKEND_SERVICES_AND_API_REFERENCE.md)** | **Backend Services & API Reference** | Cloudflare Worker endpoints (`/api/startups`, `/api/auth/*`), JWT authentication, session store, rate limiting, and request sanitization. |
| **[08_FRONTEND_AND_UX_DESIGN.md](./08_FRONTEND_AND_UX_DESIGN.md)** | **Frontend Architecture & UX Engineering** | Modular ES6 frontend, MapLibre GL / Leaflet rendering, custom SVG marker clustering, responsive split-pane/mobile drawer, and dark/light glassmorphism UI. |
| **[09_TESTING_AND_QA_STRATEGY.md](./09_TESTING_AND_QA_STRATEGY.md)** | **Testing & QA Strategy** | 38 Python pytest suites, Jest unit/modular tests, Playwright E2E browser tests, adversarial viewport testing, and regression suites. |
| **[10_DEPLOYMENT_AND_OPERATIONS_GUIDE.md](./10_DEPLOYMENT_AND_OPERATIONS_GUIDE.md)** | **Deployment & Operations Guide** | Cloudflare Wrangler configuration, D1 database schema initialization, Google OAuth Cloud Console setup, environment variables, and production deployment runbook. |
| **[11_EXPERIMENTS_AND_LESSONS_LEARNED.md](./11_EXPERIMENTS_AND_LESSONS_LEARNED.md)** | **Experiments & Lessons Learned** | Exhaustive chronological log of all technical decisions, discarded prototypes, failure modes encountered, trade-offs, and future roadmap. |

---

## 🚀 Quick Reference

### Tech Stack
* **Edge Runtime / API Gateway**: Cloudflare Workers (Node.js / V8 compatibility, ES modules)
* **Storage & Caching**: Cloudflare D1 (Serverless SQLite), Cloudflare KV (Session & rate limit storage), static JSON caching
* **Frontend**: Vanilla ES6 Modular JavaScript (`modules/state.js`, `modules/router.js`, `modules/map_manager.js`, `modules/ui_manager.js`), MapLibre GL JS / Leaflet, Tailwind / Custom Glassmorphism CSS
* **Data Processing & ML / AI Pipeline**: Python 3.9+, BeautifulSoup4, Chrome DevTools Protocol (CDP via WebSockets), requests, regex tokenizers
* **External APIs**: Google Maps Geocoding API, Esri ArcGIS World Geocoder, Photon Komoot, Google OAuth2
* **Testing Suites**: Jest (Node.js unit/mock tests), Pytest (38 pipeline & regression suites), Playwright (End-to-End browser tests)

---

### Key Workspaces & Directories
```text
starup_visualizer/
├── backend/
│   ├── worker.js              # Cloudflare Worker main entry point & asset routing
│   ├── unified_router.js      # REST API router & middleware dispatching
│   ├── startups.json          # Canonical production dataset of startups & tech jobs
│   ├── services/
│   │   ├── startup_service.js # Search, multi-office indexing, salary/exp parsing
│   │   └── auth_service.js    # Google OAuth2 PKCE, JWT tokens, session management
│   └── utils/
│       ├── jwt_helper.js      # HMAC-SHA256 token verification
│       ├── rate_limiter.js    # Sliding window rate limiter
│       └── validators.js      # Input sanitization & coordinate range guards
├── data_acquisition/
│   ├── fast_precision_geocoder.py  # 5-tier geocoder (Google Maps, Esri, Photon, Gazetteer)
│   ├── google_maps_client.py       # Cached Google Maps API client with quota limiter
│   ├── enrich_all_official_logos.py# Chrome CDP high-resolution logo extractor
│   ├── db_manager.py               # Data schema management & address cleansing
│   ├── deduplicate_startups.py     # Canonical entity deduplication
│   ├── revalidate_healing_engine.py# Hourly pipeline revalidator & link checker
│   ├── cache/                      # Persistent geocode & API quota caches
│   └── pipelines/                  # Discovery, crawling, tagging, and validation modules
├── public/
│   ├── index.html             # Single Page Application root HTML
│   └── static/
│       ├── css/style.css      # Responsive glassmorphism styling
│       ├── data/startups.json # Edge-synced startup & job catalog
│       └── js/
│           ├── app.js         # Core application bootstrap
│           └── modules/       # ES6 modules (map_manager, ui_manager, router, state, api)
├── tests/                     # 38+ comprehensive Python pipeline & regression test suites
├── tests_js/                  # Jest unit and modular tests
├── tests_e2e/                 # Playwright browser end-to-end tests
├── documentation/             # Comprehensive technical documentation (this directory)
├── package.json               # Node.js dependencies & test scripts
└── wrangler.toml              # Cloudflare Worker deployment configuration
```
