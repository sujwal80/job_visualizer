# ☁️ Cloudflare Workers & Pages Deployment Guide

This document provides step-by-step instructions for deploying the **Bangalore Startup Visualizer (WorldTech Map)** onto **Cloudflare Workers** with static asset hosting and Cloudflare KV session storage.

---

## 🏗️ Architecture Overview

| Component | Technology / Path | Role |
|---|---|---|
| **Backend API Worker** | `backend/worker.py` | Python Worker (`WorkerEntrypoint`) handling API routes (`/api/*`), CORS, CSP headers, and token-bucket rate limiting. |
| **Static Frontend Hosting** | `./public/` | Hosts SPA entrypoint (`index.html`) and static assets (`/static/css`, `/static/js`, `/static/data/startups.json`). |
| **Session & Auth Store** | Cloudflare KV (`SESSION_STORE`) | Asynchronous key-value storage for Google OAuth CSRF tokens and revoked JWT session tokens. |
| **Wrangler Config** | `wrangler.toml` | Main deployment configuration binding `ASSETS` to `./public` and `SESSION_STORE` to KV. |

---

## 🔑 Step 1: Obtain Cloudflare Credentials

### 1. Account ID
1. Log into your [Cloudflare Dashboard](https://dash.cloudflare.com/).
2. On the left menu, select **Workers & Pages**.
3. Under **Account Details** on the right side, copy your **Account ID**.

### 2. API Token
1. Go to [Cloudflare API Tokens Page](https://dash.cloudflare.com/profile/api-tokens).
2. Click **Create Token**.
3. Locate the **Edit Cloudflare Workers** template and click **Use template**.
4. Set **Account Resources** → `Include` → `All accounts` (or your target account).
5. Set **Zone Resources** → `Include` → `All zones` (or your domain).
6. Click **Continue to summary** → **Create Token**.
7. Copy the generated API Token.

---

## 📝 Step 2: Configure Environment Variables

Create a `.env` file in the project root (`/Users/singhujwal/starup_visualizer/.env`):

```env
CLOUDFLARE_ACCOUNT_ID=your_actual_account_id_here
CLOUDFLARE_API_TOKEN=your_actual_api_token_here
```

*(Note: `.env` is listed in `.gitignore` to keep credentials secure and uncommitted).*

---

## 🗄️ Step 3: Create Cloudflare KV Namespace

Run the following command in your terminal to create the production session store KV namespace:

```bash
npx wrangler kv:namespace create SESSION_STORE
```

**Output example:**
```toml
[[kv_namespaces]]
binding = "SESSION_STORE"
id = "a1b2c3d4e5f678901234567890abcdef"
```

Open [`wrangler.toml`](file:///Users/singhujwal/starup_visualizer/wrangler.toml) and replace `session_store_dummy_id` with your generated KV namespace ID:

```toml
[[kv_namespaces]]
binding = "SESSION_STORE"
id = "a1b2c3d4e5f678901234567890abcdef"
```

---

## 🧪 Step 4: Verification & Dry-Run (Local)

Before deploying live, verify compilation and test suite status:

### 1. Dry-Run Compilation Check
```bash
npx wrangler deploy --dry-run
```
*Expected Output:* Successfully bundles **8 Python modules** and reads **19 public static assets** with zero errors.

### 2. Full Test Suite Verification
```bash
python run_tests.py
```
*Expected Output:* `🏆 [SUCCESS] All 20 automated verification suites PASSED 100% CLEANLY!`

---

## 🚀 Step 5: Live Deployment

Execute the deployment command:

```bash
npx wrangler deploy
```

Upon completion, Wrangler will output your live deployment URL:
```text
Published startup-visualizer (2.45 sec)
  https://startup-visualizer.<your-subdomain>.workers.dev
```

---

## 🔍 Step 6: Post-Deployment Verification

Verify your live endpoints:

1. **SPA Frontend**: Open `https://startup-visualizer.<your-subdomain>.workers.dev/` in your browser.
2. **API Endpoint**: `GET https://startup-visualizer.<your-subdomain>.workers.dev/api/companies`
3. **Auth Status**: `GET https://startup-visualizer.<your-subdomain>.workers.dev/api/auth/status`

---

## ⚙️ Secrets Setup (OAuth & JWT)

Set your application runtime secrets using Wrangler:

```bash
npx wrangler secret put JWT_SECRET_KEY
npx wrangler secret put GOOGLE_CLIENT_ID
npx wrangler secret put GOOGLE_CLIENT_SECRET
```

---

## 🤖 Optional: CI/CD via GitHub Actions

To enable automatic deployments on `git push main`, add `.github/workflows/deploy.yml`:

```yaml
name: Deploy to Cloudflare Workers

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: npm install -g wrangler
      - run: wrangler deploy
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
```
