"""
Unified Routing Layer (Milestone 3)
Provides Request/Response adapters and a UnifiedRouter to handle routing, rate limiting,
query parameter validation, JWT authentication, and security header injection.
Compatible with Flask and Cloudflare Workers environments.
"""

import json
import math
from http.cookies import SimpleCookie
from urllib.parse import urlparse

from backend.utils.validators import _validate_query_params, _strip_redundant, _safe_float
from backend.utils.rate_limiter import _check_rate_limit
from backend.services.auth_service import (
    generate_oauth_state, validate_oauth_state, get_google_auth_url,
    exchange_code_for_user, issue_jwt_token, verify_jwt_token, revoke_jwt_token
)


class CaseInsensitiveDict:
    """A case-insensitive dictionary lookup wrapper for headers."""
    def __init__(self, data=None):
        self._store = {}
        if data:
            if isinstance(data, dict):
                for k, v in data.items():
                    self._store[k.lower()] = v
            elif isinstance(data, list):
                for k, v in data:
                    self._store[k.lower()] = v
            else:
                try:
                    for k, v in data.items():
                        self._store[k.lower()] = v
                except Exception:
                    pass

    def get(self, key, default=None):
        return self._store.get(key.lower(), default)

    def __getitem__(self, key):
        return self._store[key.lower()]

    def __contains__(self, key):
        return key.lower() in self._store

    def items(self):
        return self._store.items()


class DictMultiDict:
    """Wrapper to support getlist(key) and get(key, default, type) query params APIs."""
    def __init__(self, d):
        self._d = d or {}

    def keys(self):
        return self._d.keys()

    def getlist(self, key):
        val = self._d.get(key, [])
        if isinstance(val, list):
            return val
        return [val] if val is not None else []

    def get(self, key, default=None, type=None):
        val = self._d.get(key)
        if isinstance(val, list):
            if not val:
                return default
            val = val[0]
        if val is None:
            return default
        if type is not None:
            try:
                return type(val)
            except Exception:
                return default
        return val

    def __contains__(self, key):
        return key in self._d


class UnifiedRequest:
    """Adapter class for uniform access to incoming request properties."""
    def __init__(self, method, path, url, headers=None, query_params=None, body=None, cookies=None, testing=False, env=None, client_ip=None):
        self.method = method.upper()
        self.path = path
        self.url = url
        self.headers = CaseInsensitiveDict(headers)
        self.query_params = DictMultiDict(query_params)
        self.body = body
        self.testing = testing
        self.env = env or {}

        # Initialize cookies
        self.cookies = cookies or {}
        if not self.cookies and "cookie" in self.headers:
            cookie_str = self.headers.get("cookie") or ""
            try:
                cookie = SimpleCookie()
                cookie.load(cookie_str)
                self.cookies = {k: m.value for k, m in cookie.items()}
            except Exception:
                pass

        # Determine client IP address
        self.client_ip = (
            client_ip or
            self.headers.get("cf-connecting-ip") or
            self.headers.get("x-forwarded-for") or
            "127.0.0.1"
        )

    def get_cookie(self, name):
        return self.cookies.get(name)


class UnifiedResponse:
    """Unified response object container."""
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}
        self.cookies = []

    def set_cookie(self, name, value, max_age=None, httponly=False, secure=False, samesite=None, expires=None, path='/'):
        self.cookies.append({
            "name": name,
            "value": value,
            "max_age": max_age,
            "httponly": httponly,
            "secure": secure,
            "samesite": samesite,
            "expires": expires,
            "path": path
        })


class UnifiedRouter:
    """Unified HTTP router handling rate limits, JWT auth, validation, headers and routing."""

    async def handle_request(self, req: UnifiedRequest) -> UnifiedResponse:
        # Check rate limit
        client_ip = req.client_ip
        if req.testing and client_ip == "127.0.0.1":
            allowed, retry_after, remaining, limit_val = True, 0, 9999, 9999
        else:
            allowed, retry_after, remaining, limit_val = _check_rate_limit(client_ip)

        rate_limit_info = {'limit': limit_val, 'remaining': remaining}

        if not allowed:
            res = UnifiedResponse({"error": "Rate limit exceeded. Please try again later."}, status=429)
            res.headers['Retry-After'] = str(retry_after)
            return self._inject_headers(res, req, rate_limit_info)

        try:
            # Route matching and parameter extraction
            clean_path = "/" + req.path.strip("/")
            parts = [p for p in clean_path.split("/") if p]

            # Helper functions
            async def load_all_startups():
                assets = req.env.get("ASSETS") if isinstance(req.env, dict) else getattr(req.env, "ASSETS", None)
                if assets is not None:
                    from backend.services.startup_service import load_startups_from_assets
                    return await load_startups_from_assets(assets)
                else:
                    from backend.services.startup_service import load_startups
                    return load_startups()

            def _ids_match(id1, id2):
                if id1 is None or id2 is None:
                    return False
                s1 = str(id1).strip()
                s2 = str(id2).strip()
                if s1 == s2:
                    return True
                return s1.split('.')[0] == s2.split('.')[0]

            # Check if this is a protected route
            is_protected = False
            if len(parts) >= 2:
                # E.g. /api/user/..., /api/protected/...
                if parts[0] == 'api' and (parts[1] in ('user', 'protected') or parts[-1] == 'export'):
                    is_protected = True

            # If protected, perform authentication checks
            user = None
            if is_protected:
                token = req.get_cookie('session_token') or req.get_cookie('auth_token') or req.get_cookie('jwt_token')
                if not token:
                    auth_header = req.headers.get('Authorization') or ""
                    if auth_header.startswith('Bearer '):
                        token = auth_header.split(' ', 1)[1]

                if not token:
                    res = UnifiedResponse({"error": "Unauthenticated. Missing JWT session token."}, status=401)
                    return self._inject_headers(res, req, rate_limit_info)

                session_store = req.env.get("SESSION_STORE") if isinstance(req.env, dict) else getattr(req.env, "SESSION_STORE", None)
                user = await verify_jwt_token(token, session_store=session_store)
                if not user:
                    res = UnifiedResponse({"error": "Unauthenticated. Invalid, expired, or revoked JWT session token."}, status=401)
                    return self._inject_headers(res, req, rate_limit_info)

            # API endpoints
            # 1. GET /api/companies and /api/company
            if parts in (['api', 'companies'], ['api', 'company']) and req.method == 'GET':
                is_valid, err_msg = _validate_query_params(req.query_params)
                if not is_valid:
                    res = UnifiedResponse({"error": err_msg}, status=400)
                    return self._inject_headers(res, req, rate_limit_info)

                startups = await load_all_startups()
                min_lat = _safe_float(req.query_params.get('min_lat'))
                max_lat = _safe_float(req.query_params.get('max_lat'))
                min_lng = _safe_float(req.query_params.get('min_lng'))
                max_lng = _safe_float(req.query_params.get('max_lng'))
                limit = req.query_params.get('limit', default=500, type=int)
                city_query = (req.query_params.get('city') or '').strip().lower()
                skill_query = (req.query_params.get('skill') or '').strip().lower()
                industry_query = (req.query_params.get('industry') or '').strip().lower()
                search_query = (req.query_params.get('search') or '').strip().lower()
                dept_query = (req.query_params.get('dept') or '').strip().lower()
                exp_query = (req.query_params.get('experience') or req.query_params.get('exp') or '').strip().lower()
                has_jobs = str(req.query_params.get('has_jobs', 'false')).strip().lower() in ('true', '1', 'yes')

                from backend.services.startup_service import filter_and_sort_startups, format_startup_summary, format_lightweight_summary
                filtered = filter_and_sort_startups(
                    startups, min_lat, max_lat, min_lng, max_lng, limit,
                    city_query=city_query, skill_query=skill_query, industry_query=industry_query,
                    search_query=search_query, dept_query=dept_query, exp_query=exp_query,
                    has_jobs=has_jobs
                )

                if has_jobs:
                    light_list = [format_lightweight_summary(s) for s in filtered]
                else:
                    light_list = [format_startup_summary(s) for s in filtered]

                lean_payload = _strip_redundant(light_list)
                res = UnifiedResponse(lean_payload, status=200, headers={'Cache-Control': 'public, max-age=60'})
                return self._inject_headers(res, req, rate_limit_info)

            # 2. GET /api/companies/<id> and /api/company/<id>
            elif len(parts) == 3 and parts[0] == 'api' and parts[1] in ('companies', 'company') and parts[2] != 'export' and req.method == 'GET':
                startup_id = parts[2]
                is_valid, err_msg = _validate_query_params(req.query_params)
                if not is_valid:
                    res = UnifiedResponse({"error": err_msg}, status=400)
                    return self._inject_headers(res, req, rate_limit_info)

                startups = await load_all_startups()
                from backend.services.startup_service import format_startup_details
                for s in startups:
                    if _ids_match(s.get("id"), startup_id):
                        lean_payload = format_startup_details(s)
                        res = UnifiedResponse(lean_payload, status=200, headers={'Cache-Control': 'public, max-age=60'})
                        return self._inject_headers(res, req, rate_limit_info)

                res = UnifiedResponse({"error": "Startup not found"}, status=404)
                return self._inject_headers(res, req, rate_limit_info)

            # 3. GET /api/auth/google
            elif parts == ['api', 'auth', 'google'] and req.method == 'GET':
                session_store = req.env.get("SESSION_STORE") if isinstance(req.env, dict) else getattr(req.env, "SESSION_STORE", None)
                state = await generate_oauth_state(session_store=session_store)
                redirect_uri = req.query_params.get('redirect_uri')
                auth_url = get_google_auth_url(state, redirect_uri=redirect_uri)

                headers = {'Location': auth_url}
                if req.query_params.get('redirect', '').lower() in ('true', '1', 'yes'):
                    res = UnifiedResponse("", status=302, headers=headers)
                else:
                    res = UnifiedResponse({"auth_url": auth_url, "state": state}, status=200, headers=headers)

                res.set_cookie('oauth_state', state, max_age=600, httponly=True, secure=True, samesite='Strict')
                return self._inject_headers(res, req, rate_limit_info)

            # 4. GET/POST /api/auth/callback and /api/auth/google/callback
            elif (parts in (['api', 'auth', 'callback'], ['api', 'auth', 'google', 'callback'])) and req.method in ('GET', 'POST'):
                body_data = {}
                if req.method == 'POST':
                    if isinstance(req.body, dict):
                        body_data = req.body
                    elif isinstance(req.body, str) and req.body:
                        try:
                            body_data = json.loads(req.body)
                        except Exception:
                            pass
                    elif isinstance(req.body, bytes) and req.body:
                        try:
                            body_data = json.loads(req.body.decode("utf-8"))
                        except Exception:
                            pass

                state = req.query_params.get('state') or body_data.get('state')
                code = req.query_params.get('code') or body_data.get('code')

                session_store = req.env.get("SESSION_STORE") if isinstance(req.env, dict) else getattr(req.env, "SESSION_STORE", None)
                valid_in_store = await validate_oauth_state(state, session_store=session_store)
                cookie_state = req.get_cookie('oauth_state')
                valid_in_cookie = (state is not None and cookie_state is not None and cookie_state == state)

                if not (valid_in_store or valid_in_cookie):
                    res = UnifiedResponse({"error": "CSRF state validation failed. Invalid or expired state parameter."}, status=400)
                    return self._inject_headers(res, req, rate_limit_info)

                if not code:
                    res = UnifiedResponse({"error": "Missing authorization code."}, status=400)
                    return self._inject_headers(res, req, rate_limit_info)

                user_data = exchange_code_for_user(code)
                token = issue_jwt_token(user_data)

                payload = {
                    "message": "Authentication successful.",
                    "authenticated": True,
                    "user": {
                        "id": user_data.get("sub") or str(user_data.get("id", "")),
                        "email": user_data.get("email", ""),
                        "name": user_data.get("name", ""),
                        "picture": user_data.get("picture", "")
                    },
                    "token": token
                }
                res = UnifiedResponse(payload, status=200)
                res.set_cookie('session_token', token, max_age=3600, httponly=True, secure=True, samesite='Strict')
                res.set_cookie('oauth_state', '', expires='Thu, 01 Jan 1970 00:00:00 GMT', httponly=True, secure=True, samesite='Strict')
                return self._inject_headers(res, req, rate_limit_info)

            # 5. GET/POST /api/auth/demo_login
            elif parts == ['api', 'auth', 'demo_login'] and req.method in ('GET', 'POST'):
                demo_user = {
                    "sub": "usr_google_1001",
                    "email": "ujwal@worldtech.map",
                    "name": "Ujwal Singh",
                    "picture": "https://lh3.googleusercontent.com/a/mockphoto1"
                }
                token = issue_jwt_token(demo_user)

                headers = {}
                if req.query_params.get('redirect', '').lower() in ('true', '1', 'yes') or req.method == 'GET':
                    headers['Location'] = '/'
                    res = UnifiedResponse("", status=302, headers=headers)
                else:
                    payload = {
                        "message": "Demo sandbox authentication successful.",
                        "authenticated": True,
                        "user": demo_user,
                        "token": token
                    }
                    res = UnifiedResponse(payload, status=200, headers=headers)

                res.set_cookie('session_token', token, max_age=3600, httponly=True, secure=False, samesite='Lax')
                return self._inject_headers(res, req, rate_limit_info)

            # 6. GET /api/auth/status
            elif parts == ['api', 'auth', 'status'] and req.method == 'GET':
                token = req.get_cookie('session_token') or req.get_cookie('auth_token') or req.get_cookie('jwt_token')
                if not token:
                    auth_header = req.headers.get('Authorization') or ""
                    if auth_header.startswith('Bearer '):
                        token = auth_header.split(' ', 1)[1]

                if not token:
                    res = UnifiedResponse({"authenticated": False, "user": None, "message": "No session cookie present."}, status=200)
                    return self._inject_headers(res, req, rate_limit_info)

                session_store = req.env.get("SESSION_STORE") if isinstance(req.env, dict) else getattr(req.env, "SESSION_STORE", None)
                user = await verify_jwt_token(token, session_store=session_store)
                if not user:
                    res = UnifiedResponse({"authenticated": False, "user": None, "message": "Invalid, expired, or revoked session cookie."}, status=200)
                    return self._inject_headers(res, req, rate_limit_info)

                payload = {
                    "authenticated": True,
                    "user": {
                        "id": user.get("sub") or str(user.get("id", "")),
                        "email": user.get("email", ""),
                        "name": user.get("name", ""),
                        "picture": user.get("picture", "")
                    },
                    "expires_at": user.get("exp")
                }
                res = UnifiedResponse(payload, status=200)
                return self._inject_headers(res, req, rate_limit_info)

            # 7. GET/POST /api/auth/logout
            elif parts == ['api', 'auth', 'logout'] and req.method in ('GET', 'POST'):
                token = req.get_cookie('session_token') or req.get_cookie('auth_token') or req.get_cookie('jwt_token')
                if not token:
                    auth_header = req.headers.get('Authorization') or ""
                    if auth_header.startswith('Bearer '):
                        token = auth_header.split(' ', 1)[1]

                if token:
                    session_store = req.env.get("SESSION_STORE") if isinstance(req.env, dict) else getattr(req.env, "SESSION_STORE", None)
                    await revoke_jwt_token(token, session_store=session_store)

                res = UnifiedResponse({"message": "Successfully logged out.", "authenticated": False}, status=200)
                res.set_cookie('session_token', '', expires='Thu, 01 Jan 1970 00:00:00 GMT', httponly=True, secure=True, samesite='Strict')
                res.set_cookie('auth_token', '', expires='Thu, 01 Jan 1970 00:00:00 GMT', httponly=True, secure=True, samesite='Strict')
                res.set_cookie('jwt_token', '', expires='Thu, 01 Jan 1970 00:00:00 GMT', httponly=True, secure=True, samesite='Strict')
                return self._inject_headers(res, req, rate_limit_info)

            # 8. GET /api/user/profile or /api/protected/profile
            elif parts in (['api', 'user', 'profile'], ['api', 'protected', 'profile']) and req.method == 'GET':
                res = UnifiedResponse({"authenticated": True, "user": user}, status=200)
                return self._inject_headers(res, req, rate_limit_info)

            # 9. GET/POST/DELETE /api/user/bookmarks or /api/protected/bookmarks
            elif parts in (['api', 'user', 'bookmarks'], ['api', 'protected', 'bookmarks']) and req.method in ('GET', 'POST', 'DELETE'):
                payload = {
                    "authenticated": True,
                    "user_id": user.get("sub"),
                    "bookmarks": [],
                    "message": "Protected bookmarks endpoint accessed successfully."
                }
                res = UnifiedResponse(payload, status=200)
                return self._inject_headers(res, req, rate_limit_info)

            # 10. GET /api/company/export, /api/companies/export, or /api/protected/export
            elif parts in (['api', 'company', 'export'], ['api', 'companies', 'export'], ['api', 'protected', 'export']) and req.method == 'GET':
                startups = await load_all_startups()
                from backend.services.startup_service import format_startup_summary
                light_list = [format_startup_summary(s) for s in startups[:10]]
                payload = {
                    "authenticated": True,
                    "export_count": len(light_list),
                    "data": light_list
                }
                res = UnifiedResponse(payload, status=200)
                return self._inject_headers(res, req, rate_limit_info)

            # Handle 404
            res = UnifiedResponse({"error": "Not Found"}, status=404)
            return self._inject_headers(res, req, rate_limit_info)

        except Exception as e:
            res = UnifiedResponse({"error": "Internal server error"}, status=500)
            return self._inject_headers(res, req, rate_limit_info)

    def _inject_headers(self, response: UnifiedResponse, req: UnifiedRequest, rate_limit_info=None) -> UnifiedResponse:
        headers = self.inject_security_headers(response.headers, req.path)

        if rate_limit_info:
            headers['x-ratelimit-limit'] = str(rate_limit_info.get('limit', 120))
            headers['x-ratelimit-remaining'] = str(rate_limit_info.get('remaining', 120))

        path = req.path
        if path.startswith('/api/company') or path.startswith('/api/companies'):
            from backend.services.startup_service import get_data_version
            try:
                headers['x-data-version'] = get_data_version()
            except Exception:
                headers['x-data-version'] = "0"
            
            expose_headers = headers.get('access-control-expose-headers', '')
            if expose_headers:
                if 'X-Data-Version' not in expose_headers:
                    headers['access-control-expose-headers'] = f"{expose_headers}, X-Data-Version"
            else:
                headers['access-control-expose-headers'] = 'X-Data-Version, X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After'

        if response.status >= 400:
            headers['cache-control'] = 'no-store'

        response.headers = headers
        return response

    @staticmethod
    def inject_security_headers(headers: dict, path: str) -> dict:
        headers_lower = {k.lower(): v for k, v in headers.items()}

        if path.startswith('/api/'):
            csp = (
                "default-src 'self' https://*.tile.openstreetmap.org https://cdnjs.cloudflare.com https://cdn.tailwindcss.com; "
                "script-src 'self' https://unpkg.com https://cdnjs.cloudflare.com https://cdn.tailwindcss.com; "
                "style-src 'self' https://fonts.googleapis.com https://unpkg.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://cdn.tailwindcss.com; "
                "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com https://unpkg.com https://*.cartocdn.com; "
                "img-src 'self' data: blob: https: http:; "
                "connect-src 'self' https://*.cartocdn.com https://*.basemaps.cartocdn.com https://basemaps.cartocdn.com https://*.maplibre.org https://*.arcgisonline.com https://*.openstreetmap.org https://*.tile.openstreetmap.org blob: data:; "
                "worker-src 'self' blob:; "
                "child-src 'self' blob:; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "frame-ancestors 'self';"
            )
        else:
            csp = (
                "default-src 'self' https://*.tile.openstreetmap.org https://cdnjs.cloudflare.com https://cdn.tailwindcss.com; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com https://cdnjs.cloudflare.com https://cdn.tailwindcss.com; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://cdn.tailwindcss.com; "
                "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com https://unpkg.com https://*.cartocdn.com; "
                "img-src 'self' data: blob: https: http:; "
                "connect-src 'self' https://*.cartocdn.com https://*.basemaps.cartocdn.com https://basemaps.cartocdn.com https://*.maplibre.org https://*.arcgisonline.com https://*.openstreetmap.org https://*.tile.openstreetmap.org blob: data:; "
                "worker-src 'self' blob:; "
                "child-src 'self' blob:; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "frame-ancestors 'self';"
            )

        headers_lower['content-security-policy'] = csp
        headers_lower['x-content-type-options'] = 'nosniff'
        headers_lower['x-frame-options'] = 'SAMEORIGIN'
        headers_lower['referrer-policy'] = 'strict-origin-when-cross-origin'
        headers_lower['access-control-allow-origin'] = '*'
        headers_lower['access-control-allow-methods'] = 'GET, POST, DELETE, OPTIONS'
        headers_lower['access-control-allow-headers'] = 'Content-Type, Authorization, Accept, Accept-Encoding'
        headers_lower['strict-transport-security'] = 'max-age=31536000; includeSubDomains'

        vary = headers_lower.get('vary', '')
        if not vary:
            headers_lower['vary'] = 'Accept-Encoding'
        elif 'Accept-Encoding' not in vary:
            headers_lower['vary'] = f'{vary}, Accept-Encoding'

        return headers_lower
