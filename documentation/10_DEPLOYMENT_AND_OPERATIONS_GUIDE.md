# Deployment & Operations Guide

> Production deployment runbook, Cloudflare Workers configuration, D1 database migrations, KV namespace setup, Google OAuth Cloud Console configuration, and operational monitoring.

---

## 1. Production Architecture Summary

* **Platform**: Cloudflare Workers (Global Serverless Edge)
* **Custom Domain**: `https://mapmyjob.in`
* **Static Assets**: Cloudflare Asset Binding (`./public`)
* **Relational Storage**: Cloudflare D1 Database (`jobs-visualizer-db`)
* **Session Store**: Cloudflare KV (`SESSION_STORE`)
* **Authentication**: Google OAuth2 PKCE Flow

---

## 2. Configuration Files

### 2.1 `wrangler.toml`
```toml
name = "job-visualizer"
main = "backend/worker.js"
compatibility_date = "2024-09-19"
compatibility_flags = [ "nodejs_compat" ]

[vars]
ENVIRONMENT = "production"
GOOGLE_REDIRECT_URI = "https://mapmyjob.in/api/auth/callback"
GOOGLE_CLIENT_ID = "614597180918-81b3rlfuesd82bkdoltga92sb9vplfr5.apps.googleusercontent.com"

[assets]
directory = "./public"
binding = "ASSETS"

[[kv_namespaces]]
binding = "SESSION_STORE"
id = "ae27dac64a534dc485511d6911cae2fd"

[[d1_databases]]
binding = "DB"
database_name = "jobs-visualizer-db"
database_id = "3f8b6152-4315-4ce1-a449-b2014c740bf5"
```

### 2.2 Relational Database Schema (`schema.sql`)
```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    google_id TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    avatar_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    startup_id INTEGER NOT NULL,
    job_title TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_bookmarks ON bookmarks(user_id);
```

---

## 3. Step-by-Step Deployment Runbook

### Step 1: Initialize Cloudflare Infrastructure
```bash
# 1. Login to Cloudflare via Wrangler CLI
npx wrangler login

# 2. Create D1 Database (if not already created)
npx wrangler d1 create jobs-visualizer-db

# 3. Apply SQL Schema to Production D1
npx wrangler d1 execute jobs-visualizer-db --file=./schema.sql

# 4. Create KV Namespace for Sessions
npx wrangler kv:namespace create "SESSION_STORE"
```

### Step 2: Configure Environment Secrets
Secrets must be stored securely using Wrangler Secrets (never commit secrets to git):
```bash
# Set Google OAuth Client Secret
npx wrangler secret put GOOGLE_CLIENT_SECRET

# Set JWT Signing Secret
npx wrangler secret put JWT_SECRET
```

### Step 3: Configure Google Cloud OAuth Console
1. Navigate to **Google Cloud Console ➔ APIs & Services ➔ Credentials**.
2. Under **Authorized JavaScript Origins**, add:
   - `https://mapmyjob.in`
   - `http://localhost:8787` (for local development)
3. Under **Authorized Redirect URIs**, add:
   - `https://mapmyjob.in/api/auth/callback`
   - `http://localhost:8787/api/auth/callback`

### Step 4: Synchronize Production Dataset & Deploy
```bash
# 1. Synchronize backend database to public static folder
cp backend/startups.json public/static/data/startups.json

# 2. Deploy Cloudflare Worker & Static Assets to Production
npx wrangler deploy
```

---

## 4. Local Development

To run the full stack locally with hot reloading:

```bash
# Start local Cloudflare Worker development server
npm run dev
# Server listening at http://localhost:8787
```

---

## 5. Operations & Health Monitoring

* **Health Endpoint**: `https://mapmyjob.in/api/health`
* **Real-time Worker Logs**:
  ```bash
  npx wrangler tail
  ```
* **Database Querying via CLI**:
  ```bash
  npx wrangler d1 execute jobs-visualizer-db --command="SELECT COUNT(*) FROM users;"
  ```
