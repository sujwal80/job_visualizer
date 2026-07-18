"""
Cloudflare Workers Entrypoint Application
Implements WorkerEntrypoint to route API endpoints, handle OAuth callbacks,
session KV verification, and static asset delivery via the ASSETS binding.
"""

import json
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs, urlunparse
from backend.config import setup_config
from backend.services.startup_service import (
    load_startups_from_assets, filter_and_sort_startups,
    format_startup_summary, format_startup_details,
    format_lightweight_summary, get_data_version
)
from backend.services.auth_service import (
    generate_oauth_state, validate_oauth_state, get_google_auth_url,
    exchange_code_for_user, issue_jwt_token, verify_jwt_token, revoke_jwt_token
)
from backend.utils.rate_limiter import _check_rate_limit
from backend.utils.validators import _validate_query_params, _strip_redundant, _safe_float

try:
    from js import Response, Request, Headers
except ImportError:
    class Headers:
        def __init__(self, headers=None):
            self._headers = []
            if headers:
                if isinstance(headers, dict):
                    for k, v in headers.items():
                        self._headers.append((k.lower(), str(v)))
                elif isinstance(headers, list):
                    for k, v in headers:
                        self._headers.append((k.lower(), str(v)))
        def set(self, name, value):
            name_lower = name.lower()
            self._headers = [(k, v) for k, v in self._headers if k != name_lower]
            self._headers.append((name_lower, str(value)))
        def append(self, name, value):
            self._headers.append((name.lower(), str(value)))
        def get(self, name):
            name_lower = name.lower()
            for k, v in self._headers:
                if k == name_lower:
                    return v
            return None
        def entries(self):
            return self._headers

    class Response:
        def __init__(self, body, status=200, headers=None):
            self.body = body
            self.status = status
            if isinstance(headers, Headers):
                self.headers = headers
            else:
                self.headers = Headers(headers)

    class Request:
        def __init__(self, url, method="GET", headers=None, body=None):
            self.url = url
            self.method = method
            if isinstance(headers, Headers):
                self.headers = headers
            else:
                self.headers = Headers(headers)
            self.body = body

class DictMultiDict:
    def __init__(self, d):
        self._d = d or {}
    def keys(self):
        return self._d.keys()
    def getlist(self, key):
        return self._d.get(key, [])
    def get(self, key, default=None, type=None):
        vals = self._d.get(key)
        if not vals:
            return default
        val = vals[0]
        if type is not None:
            try:
                return type(val)
            except Exception:
                return default
        return val
    def __contains__(self, key):
        return key in self._d

def get_cookie(request, cookie_name):
    cookie_str = request.headers.get("Cookie") or ""
    cookie = SimpleCookie()
    cookie.load(cookie_str)
    morsel = cookie.get(cookie_name)
    return morsel.value if morsel else None

class WorkerEntrypoint:
    def __init__(self, env):
        self.env = env
        setup_config(env)

    async def fetch(self, request):
        parsed_url = urlparse(request.url)
        path = parsed_url.path
        method = request.method.upper()

        # CORS preflight options
        if method == "OPTIONS":
            headers = Headers()
            headers.set('Access-Control-Allow-Origin', '*')
            headers.set('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
            headers.set('Access-Control-Allow-Headers', 'Content-Type, Authorization, Accept, Accept-Encoding')
            headers.set('Access-Control-Max-Age', '86400')
            return Response("", status=204, headers=headers)

        # Forward non-API requests (static frontend templates and assets) to ASSETS
        if not path.startswith('/api/'):
            if path in ('/', '/jobs', '/map'):
                parsed_req = urlparse(request.url)
                new_url = urlunparse(parsed_req._replace(path='/index.html'))
                asset_request = Request(new_url, method=request.method, headers=request.headers)
                asset_response = await self.env.ASSETS.fetch(asset_request)
            else:
                asset_response = await self.env.ASSETS.fetch(request)
            return self._inject_headers(asset_response, path)

        # Rate Limiting via Connecting IP
        client_ip = request.headers.get("CF-Connecting-IP") or "127.0.0.1"
        allowed, retry_after, remaining, limit_val = _check_rate_limit(client_ip)
        rate_limit_info = {'limit': limit_val, 'remaining': remaining}
        
        if not allowed:
            headers = Headers()
            headers.set('Retry-After', str(retry_after))
            resp = Response(json.dumps({"error": "Rate limit exceeded. Please try again later."}), status=429, headers=headers)
            return self._inject_headers(resp, path, rate_limit_info)

        # API Routing and endpoint implementation
        try:
            # 1. GET /api/companies and /api/company
            if path in ('/api/companies', '/api/company') and method == 'GET':
                query_params = parse_qs(parsed_url.query)
                args = DictMultiDict(query_params)
                is_valid, err_msg = _validate_query_params(args)
                if not is_valid:
                    return self._json_response({"error": err_msg}, status=400, path=path, rate_limit_info=rate_limit_info)

                startups = await load_startups_from_assets(self.env.ASSETS)
                
                min_lat = _safe_float(args.get('min_lat'))
                max_lat = _safe_float(args.get('max_lat'))
                min_lng = _safe_float(args.get('min_lng'))
                max_lng = _safe_float(args.get('max_lng'))
                limit = args.get('limit', default=500, type=int)
                city_query = (args.get('city') or '').strip().lower()
                skill_query = (args.get('skill') or '').strip().lower()
                industry_query = (args.get('industry') or '').strip().lower()
                search_query = (args.get('search') or '').strip().lower()
                dept_query = (args.get('dept') or '').strip().lower()
                exp_query = (args.get('experience') or args.get('exp') or '').strip().lower()
                has_jobs = str(args.get('has_jobs', 'false')).strip().lower() in ('true', '1', 'yes')

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
                headers = Headers()
                headers.set('Cache-Control', 'public, max-age=60')
                return self._json_response(lean_payload, headers=headers, path=path, rate_limit_info=rate_limit_info)

            # 2. GET /api/companies/<id> and /api/company/<id>
            elif (path.startswith('/api/companies/') or path.startswith('/api/company/')) and method == 'GET':
                parts = path.strip('/').split('/')
                if len(parts) == 3:
                    startup_id = parts[2]
                else:
                    return self._json_response({"error": "Invalid company path"}, status=400, path=path, rate_limit_info=rate_limit_info)

                query_params = parse_qs(parsed_url.query)
                args = DictMultiDict(query_params)
                is_valid, err_msg = _validate_query_params(args)
                if not is_valid:
                    return self._json_response({"error": err_msg}, status=400, path=path, rate_limit_info=rate_limit_info)

                startups = await load_startups_from_assets(self.env.ASSETS)
                
                def _ids_match(id1, id2):
                    if id1 is None or id2 is None:
                        return False
                    s1 = str(id1).strip()
                    s2 = str(id2).strip()
                    if s1 == s2:
                        return True
                    return s1.split('.')[0] == s2.split('.')[0]

                for s in startups:
                    if _ids_match(s.get("id"), startup_id):
                        lean_payload = format_startup_details(s)
                        headers = Headers()
                        headers.set('Cache-Control', 'public, max-age=60')
                        return self._json_response(lean_payload, headers=headers, path=path, rate_limit_info=rate_limit_info)

                return self._json_response({"error": "Startup not found"}, status=404, path=path, rate_limit_info=rate_limit_info)

            # 3. GET /api/auth/google
            elif path == '/api/auth/google' and method == 'GET':
                session_store = getattr(self.env, 'SESSION_STORE', None)
                state = await generate_oauth_state(session_store=session_store)
                query_params = parse_qs(parsed_url.query)
                args = DictMultiDict(query_params)
                redirect_uri = args.get('redirect_uri')
                auth_url = get_google_auth_url(state, redirect_uri=redirect_uri)

                headers = Headers()
                if args.get('redirect', '').lower() in ('true', '1', 'yes'):
                    headers.set('Location', auth_url)
                    headers.append('Set-Cookie', f'oauth_state={state}; Max-Age=600; HttpOnly; Secure; SameSite=Strict; Path=/')
                    resp = Response("", status=302, headers=headers)
                else:
                    headers.set('Location', auth_url)
                    headers.append('Set-Cookie', f'oauth_state={state}; Max-Age=600; HttpOnly; Secure; SameSite=Strict; Path=/')
                    resp = Response(json.dumps({"auth_url": auth_url, "state": state}), status=200, headers=headers)
                
                return self._inject_headers(resp, path, rate_limit_info)

            # 4. GET/POST /api/auth/callback and /api/auth/google/callback
            elif path in ('/api/auth/callback', '/api/auth/google/callback') and method in ('GET', 'POST'):
                query_params = parse_qs(parsed_url.query)
                args = DictMultiDict(query_params)
                
                body_data = {}
                if method == 'POST':
                    if hasattr(request, "text"):
                        try:
                            body_str = await request.text()
                        except Exception:
                            body_str = ""
                    else:
                        body_str = getattr(request, "body", "")
                    
                    if hasattr(body_str, "decode"):
                        body_str = body_str.decode("utf-8")
                    if isinstance(body_str, str) and body_str:
                        try:
                            body_data = json.loads(body_str)
                        except Exception:
                            pass
                    elif isinstance(body_str, dict):
                        body_data = body_str

                state = args.get('state') or body_data.get('state')
                code = args.get('code') or body_data.get('code')

                session_store = getattr(self.env, 'SESSION_STORE', None)
                valid_in_store = await validate_oauth_state(state, session_store=session_store)
                cookie_state = get_cookie(request, 'oauth_state')
                valid_in_cookie = (state is not None and cookie_state is not None and cookie_state == state)

                if not (valid_in_store or valid_in_cookie):
                    return self._json_response({"error": "CSRF state validation failed. Invalid or expired state parameter."}, status=400, path=path, rate_limit_info=rate_limit_info)

                if not code:
                    return self._json_response({"error": "Missing authorization code."}, status=400, path=path, rate_limit_info=rate_limit_info)

                user_data = exchange_code_for_user(code)
                token = issue_jwt_token(user_data)

                headers = Headers()
                headers.append('Set-Cookie', f'session_token={token}; Max-Age=3600; HttpOnly; Secure; SameSite=Strict; Path=/')
                headers.append('Set-Cookie', 'oauth_state=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; Secure; SameSite=Strict; Path=/')
                
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
                return self._json_response(payload, status=200, headers=headers, path=path, rate_limit_info=rate_limit_info)

            # 5. GET/POST /api/auth/demo_login
            elif path == '/api/auth/demo_login' and method in ('GET', 'POST'):
                query_params = parse_qs(parsed_url.query)
                args = DictMultiDict(query_params)
                
                demo_user = {
                    "sub": "usr_google_1001",
                    "email": "ujwal@worldtech.map",
                    "name": "Ujwal Singh",
                    "picture": "https://lh3.googleusercontent.com/a/mockphoto1"
                }
                token = issue_jwt_token(demo_user)

                headers = Headers()
                headers.append('Set-Cookie', f'session_token={token}; Max-Age=3600; HttpOnly; SameSite=Lax; Path=/')
                
                if args.get('redirect', '').lower() in ('true', '1', 'yes') or method == 'GET':
                    headers.set('Location', '/')
                    resp = Response("", status=302, headers=headers)
                else:
                    payload = {
                        "message": "Demo sandbox authentication successful.",
                        "authenticated": True,
                        "user": demo_user,
                        "token": token
                    }
                    resp = Response(json.dumps(payload), status=200, headers=headers)
                
                return self._inject_headers(resp, path, rate_limit_info)

            # 6. GET /api/auth/status
            elif path == '/api/auth/status' and method == 'GET':
                token = get_cookie(request, 'session_token') or get_cookie(request, 'auth_token') or get_cookie(request, 'jwt_token')
                if not token:
                    auth_header = request.headers.get('Authorization') or ""
                    if auth_header.startswith('Bearer '):
                        token = auth_header.split(' ', 1)[1]

                if not token:
                    return self._json_response({"authenticated": False, "user": None, "message": "No session cookie present."}, status=200, path=path, rate_limit_info=rate_limit_info)

                session_store = getattr(self.env, 'SESSION_STORE', None)
                user = await verify_jwt_token(token, session_store=session_store)
                if not user:
                    return self._json_response({"authenticated": False, "user": None, "message": "Invalid, expired, or revoked session cookie."}, status=200, path=path, rate_limit_info=rate_limit_info)

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
                return self._json_response(payload, status=200, path=path, rate_limit_info=rate_limit_info)

            # 7. GET/POST /api/auth/logout
            elif path == '/api/auth/logout' and method in ('GET', 'POST'):
                token = get_cookie(request, 'session_token') or get_cookie(request, 'auth_token') or get_cookie(request, 'jwt_token')
                if not token:
                    auth_header = request.headers.get('Authorization') or ""
                    if auth_header.startswith('Bearer '):
                        token = auth_header.split(' ', 1)[1]

                if token:
                    session_store = getattr(self.env, 'SESSION_STORE', None)
                    await revoke_jwt_token(token, session_store=session_store)

                headers = Headers()
                headers.append('Set-Cookie', 'session_token=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; Secure; SameSite=Strict; Path=/')
                headers.append('Set-Cookie', 'auth_token=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; Secure; SameSite=Strict; Path=/')
                headers.append('Set-Cookie', 'jwt_token=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; Secure; SameSite=Strict; Path=/')
                
                payload = {"message": "Successfully logged out.", "authenticated": False}
                return self._json_response(payload, status=200, headers=headers, path=path, rate_limit_info=rate_limit_info)

            # 8. Protected API endpoints: GET /api/user/profile
            elif path in ('/api/user/profile', '/api/protected/profile') and method == 'GET':
                user = await self._authenticate_request(request)
                if not user:
                    return self._json_response({"error": "Unauthenticated. Missing or invalid JWT session token."}, status=401, path=path, rate_limit_info=rate_limit_info)
                return self._json_response({"authenticated": True, "user": user}, status=200, path=path, rate_limit_info=rate_limit_info)

            # 9. Protected API endpoints: GET/POST/DELETE /api/user/bookmarks
            elif path in ('/api/user/bookmarks', '/api/protected/bookmarks') and method in ('GET', 'POST', 'DELETE'):
                user = await self._authenticate_request(request)
                if not user:
                    return self._json_response({"error": "Unauthenticated. Missing or invalid JWT session token."}, status=401, path=path, rate_limit_info=rate_limit_info)
                payload = {
                    "authenticated": True,
                    "user_id": user.get("sub"),
                    "bookmarks": [],
                    "message": "Protected bookmarks endpoint accessed successfully."
                }
                return self._json_response(payload, status=200, path=path, rate_limit_info=rate_limit_info)

            # 10. Protected API endpoints: GET /api/company/export
            elif path in ('/api/company/export', '/api/companies/export', '/api/protected/export') and method == 'GET':
                user = await self._authenticate_request(request)
                if not user:
                    return self._json_response({"error": "Unauthenticated. Missing or invalid JWT session token."}, status=401, path=path, rate_limit_info=rate_limit_info)
                
                startups = await load_startups_from_assets(self.env.ASSETS)
                light_list = [format_startup_summary(s) for s in startups[:10]]
                payload = {
                    "authenticated": True,
                    "export_count": len(light_list),
                    "data": light_list
                }
                return self._json_response(payload, status=200, path=path, rate_limit_info=rate_limit_info)

            else:
                return self._json_response({"error": "Not Found"}, status=404, path=path, rate_limit_info=rate_limit_info)

        except Exception as e:
            return self._json_response({"error": "Internal server error"}, status=500, path=path, rate_limit_info=rate_limit_info)

    async def _authenticate_request(self, request):
        token = get_cookie(request, 'session_token') or get_cookie(request, 'auth_token') or get_cookie(request, 'jwt_token')
        if not token:
            auth_header = request.headers.get('Authorization') or ""
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ', 1)[1]
        if not token:
            return None
        session_store = getattr(self.env, 'SESSION_STORE', None)
        return await verify_jwt_token(token, session_store=session_store)

    def _json_response(self, data, status=200, headers=None, path="", rate_limit_info=None):
        if headers is None:
            headers = Headers()
        headers.set('Content-Type', 'application/json')
        resp = Response(json.dumps(data), status=status, headers=headers)
        return self._inject_headers(resp, path, rate_limit_info)

    def _inject_headers(self, response, path, rate_limit_info=None):
        headers_dict = {}
        if hasattr(response, "headers"):
            if hasattr(response.headers, "entries"):
                try:
                    for k, v in response.headers.entries():
                        headers_dict[k.lower()] = v
                except Exception:
                    pass
            if not headers_dict and hasattr(response.headers, "_headers"):
                headers_dict = {k: v for k, v in response.headers._headers}
            elif not headers_dict and isinstance(response.headers, dict):
                headers_dict = {k.lower(): v for k, v in response.headers.items()}

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

        headers_dict['content-security-policy'] = csp
        headers_dict['x-content-type-options'] = 'nosniff'
        headers_dict['x-frame-options'] = 'SAMEORIGIN'
        headers_dict['referrer-policy'] = 'strict-origin-when-cross-origin'
        headers_dict['access-control-allow-origin'] = '*'
        headers_dict['access-control-allow-methods'] = 'GET, POST, DELETE, OPTIONS'
        headers_dict['access-control-allow-headers'] = 'Content-Type, Authorization, Accept, Accept-Encoding'
        headers_dict['strict-transport-security'] = 'max-age=31536000; includeSubDomains'

        vary = headers_dict.get('vary', '')
        if not vary:
            headers_dict['vary'] = 'Accept-Encoding'
        elif 'Accept-Encoding' not in vary:
            headers_dict['vary'] = f'{vary}, Accept-Encoding'

        if rate_limit_info:
            headers_dict['x-ratelimit-limit'] = str(rate_limit_info.get('limit', 120))
            headers_dict['x-ratelimit-remaining'] = str(rate_limit_info.get('remaining', 120))

        if path.startswith('/api/company') or path.startswith('/api/companies'):
            headers_dict['x-data-version'] = get_data_version()
            expose_headers = headers_dict.get('access-control-expose-headers', '')
            if expose_headers:
                if 'X-Data-Version' not in expose_headers:
                    headers_dict['access-control-expose-headers'] = f"{expose_headers}, X-Data-Version"
            else:
                headers_dict['access-control-expose-headers'] = 'X-Data-Version, X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After'

        if response.status >= 400:
            headers_dict['cache-control'] = 'no-store'

        try:
            from js import Headers as JSHeaders, Response as JSResponse
            new_headers = JSHeaders()
        except ImportError:
            JSHeaders = Headers
            JSResponse = Response
            new_headers = JSHeaders()

        for k, v in headers_dict.items():
            if k == 'set-cookie':
                pass
            else:
                new_headers.set(k, v)

        if hasattr(response, "headers") and hasattr(response.headers, "entries"):
            try:
                for k, v in response.headers.entries():
                    if k.lower() == 'set-cookie':
                        new_headers.append('Set-Cookie', v)
            except Exception:
                pass
        elif hasattr(response, "headers") and hasattr(response.headers, "_headers"):
            for k, v in response.headers._headers:
                if k == 'set-cookie':
                    new_headers.append('Set-Cookie', v)

        body = getattr(response, "body", "")
        return JSResponse(body, status=response.status, headers=new_headers)
