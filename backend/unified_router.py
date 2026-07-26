"""
Unified Routing Layer (Milestone 3)
Provides Request/Response adapters and a UnifiedRouter to handle routing, rate limiting,
query parameter validation, JWT authentication, and security header injection.
Compatible with Flask and Cloudflare Workers environments.
"""

import json
from http.cookies import SimpleCookie
from urllib.parse import urlparse

def get_request_origin(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass
    return "http://127.0.0.1:5001"

from backend.utils.validators import _validate_query_params, _strip_redundant, _safe_float
from backend.utils.rate_limiter import _check_rate_limit
from backend.services.auth_service import (
    generate_oauth_state, validate_oauth_state, get_google_auth_url,
    exchange_code_for_user, issue_jwt_token, verify_jwt_token, revoke_jwt_token
)

def is_safe_redirect(url):
    if not url:
        return False
    # Must start with / and not start with // or /\ to prevent protocol-relative redirects
    return url.startswith('/') and not url.startswith('//') and not url.startswith('/\\')

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

        # 1. Parse session token early
        token = req.get_cookie('session_token') or req.get_cookie('auth_token') or req.get_cookie('jwt_token')
        if not token:
            auth_header = req.headers.get('Authorization') or ""
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ', 1)[1]

        # 2. Verify token early
        user = None
        if token:
            session_store = None
            if req.env:
                session_store = req.env.get("SESSION_STORE") if isinstance(req.env, dict) else getattr(req.env, "SESSION_STORE", None)
            if not session_store:
                from backend import config
                session_store = getattr(config, 'SESSION_STORE', None)
            user = await verify_jwt_token(token, session_store=session_store)

        # Resolve DB
        db = None
        if req.env:
            db = req.env.get("DB") if isinstance(req.env, dict) else getattr(req.env, "DB", None)
        if not db:
            from backend import config
            db = getattr(config, 'DB', None)

        # 3. Determine rate limit key and value
        from backend import config
        if user:
            user_id = user.get("sub") or str(user.get("id", ""))
            rate_key = f"auth:{user_id}"
            limit_val = config.RATE_LIMIT_AUTH
        else:
            rate_key = f"anon:{client_ip}"
            limit_val = config.RATE_LIMIT_ANON

        # 4. Check rate limit
        if req.testing and client_ip in ("127.0.0.1", "::1", "localhost"):
            allowed, retry_after, remaining, limit_val = True, 0, 9999, limit_val
        else:
            allowed, retry_after, remaining, limit_val = _check_rate_limit(rate_key, limit=limit_val)
            if not allowed:
                print(f"[DEBUG RateLimit Blocked] rate_key={rate_key!r} req.testing={req.testing!r} path={req.path!r}", flush=True)

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
                from backend.services.startup_service import load_startups_unified
                return await load_startups_unified(req.env)

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
            if is_protected:
                if not token:
                    res = UnifiedResponse({"error": "Unauthenticated. Missing JWT session token."}, status=401)
                    return self._inject_headers(res, req, rate_limit_info)
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
                role_query = (req.query_params.get('role') or '').strip().lower()
                salary_min_query = _safe_float(req.query_params.get('salary_min'))
                exp_level_query = (req.query_params.get('exp_level') or '').strip().lower()
                work_type_query = (req.query_params.get('work_type') or '').strip().lower()

                from backend.services.startup_service import filter_and_sort_startups, format_startup_summary, format_lightweight_summary
                filtered = filter_and_sort_startups(
                    startups, min_lat, max_lat, min_lng, max_lng, limit,
                    city_query=city_query, skill_query=skill_query, industry_query=industry_query,
                    search_query=search_query, dept_query=dept_query, exp_query=exp_query,
                    has_jobs=has_jobs,
                    role_query=role_query, salary_min_query=salary_min_query,
                    exp_level_query=exp_level_query, work_type_query=work_type_query
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
                from backend.services.startup_service import format_startup_details, _parse_max_salary, _match_exp_level, _match_work_type
                
                role_query = (req.query_params.get('role') or '').strip().lower()
                salary_min_query = _safe_float(req.query_params.get('salary_min'))
                exp_level_query = (req.query_params.get('exp_level') or '').strip().lower()
                work_type_query = (req.query_params.get('work_type') or '').strip().lower()
                has_job_filters = bool(role_query or salary_min_query is not None or exp_level_query or work_type_query)
                
                for s in startups:
                    if _ids_match(s.get("id"), startup_id):
                        if has_job_filters:
                            job_openings = s.get("job_openings") or []
                            filtered_jobs = []
                            for j in job_openings:
                                if not isinstance(j, dict):
                                    continue
                                if role_query and role_query not in str(j.get("title") or "").lower():
                                    continue
                                if salary_min_query is not None:
                                    max_sal = _parse_max_salary(j.get("salary"))
                                    if max_sal is None or max_sal < salary_min_query:
                                        continue
                                if exp_level_query and not _match_exp_level(str(j.get("experience") or ""), exp_level_query):
                                    continue
                                if work_type_query and not _match_work_type(j, work_type_query, is_remote_office=s.get("is_remote_office")):
                                    continue
                                filtered_jobs.append(j)
                            
                            target_startup = dict(s)
                            target_startup["job_openings"] = filtered_jobs
                        else:
                            target_startup = s
                            
                        lean_payload = format_startup_details(target_startup)
                        res = UnifiedResponse(lean_payload, status=200, headers={'Cache-Control': 'public, max-age=60'})
                        return self._inject_headers(res, req, rate_limit_info)

                res = UnifiedResponse({"error": "Startup not found"}, status=404)
                return self._inject_headers(res, req, rate_limit_info)

            # 3. GET /api/auth/google
            elif parts == ['api', 'auth', 'google'] and req.method == 'GET':
                session_store = None
                if req.env:
                    session_store = req.env.get("SESSION_STORE") if isinstance(req.env, dict) else getattr(req.env, "SESSION_STORE", None)
                if not session_store:
                    from backend import config
                    session_store = getattr(config, 'SESSION_STORE', None)
                state_token = await generate_oauth_state(session_store=session_store)
                next_path = req.query_params.get('next') or '/'
                # Validate redirect to prevent Open Redirect vulnerabilities
                if not is_safe_redirect(next_path):
                    next_path = '/'
                combined_state = f"{state_token}:{next_path}"
                request_origin = get_request_origin(req.url)
                redirect_uri = req.query_params.get('redirect_uri') or f"{request_origin}/api/auth/callback"
                auth_url = get_google_auth_url(combined_state, redirect_uri=redirect_uri)

                headers = {'Location': auth_url}
                if req.query_params.get('redirect', '').lower() in ('true', '1', 'yes'):
                    res = UnifiedResponse("", status=302, headers=headers)
                else:
                    res = UnifiedResponse({"auth_url": auth_url, "state": combined_state}, status=200, headers=headers)

                is_prod = (config.ENVIRONMENT == 'production')
                res.set_cookie('oauth_state', state_token, max_age=600, httponly=True, secure=is_prod, samesite='Lax')
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

                combined_state = req.query_params.get('state') or body_data.get('state') or ""
                code = req.query_params.get('code') or body_data.get('code')

                if ':' in combined_state:
                    state_token, next_path = combined_state.split(':', 1)
                else:
                    state_token = combined_state
                    next_path = '/'

                # Validate redirect to prevent Open Redirect vulnerabilities
                if not is_safe_redirect(next_path):
                    next_path = '/'

                session_store = None
                if req.env:
                    session_store = req.env.get("SESSION_STORE") if isinstance(req.env, dict) else getattr(req.env, "SESSION_STORE", None)
                if not session_store:
                    from backend import config
                    session_store = getattr(config, 'SESSION_STORE', None)

                cookie_state = req.get_cookie('oauth_state')
                # Enforce strict cookie state matching to prevent OAuth CSRF (session fixation)
                if not cookie_state or cookie_state != state_token:
                    res = UnifiedResponse({"error": "CSRF state validation failed. Cookie state mismatch or missing."}, status=400)
                    return self._inject_headers(res, req, rate_limit_info)

                # Consume the state from store/in-memory
                valid_in_store = await validate_oauth_state(state_token, session_store=session_store)
                if not valid_in_store:
                    res = UnifiedResponse({"error": "CSRF state validation failed. State token expired or already used."}, status=400)
                    return self._inject_headers(res, req, rate_limit_info)

                if not code:
                    res = UnifiedResponse({"error": "Missing authorization code."}, status=400)
                    return self._inject_headers(res, req, rate_limit_info)

                request_origin = get_request_origin(req.url)
                redirect_uri = req.query_params.get('redirect_uri') or f"{request_origin}/api/auth/callback"
                try:
                    user_data = await exchange_code_for_user(code, redirect_uri=redirect_uri)
                except ValueError as e:
                    res = UnifiedResponse({"error": str(e)}, status=400)
                    return self._inject_headers(res, req, rate_limit_info)
                token = issue_jwt_token(user_data)

                res = UnifiedResponse("", status=302, headers={'Location': next_path})
                is_prod = (config.ENVIRONMENT == 'production')
                res.set_cookie('session_token', token, max_age=3600, httponly=True, secure=is_prod, samesite='Strict')
                res.set_cookie('oauth_state', '', expires='Thu, 01 Jan 1970 00:00:00 GMT', httponly=True, secure=is_prod, samesite='Lax')
                return self._inject_headers(res, req, rate_limit_info)

            # 5. GET/POST /api/auth/demo_login
            elif parts == ['api', 'auth', 'demo_login'] and req.method in ('GET', 'POST'):
                from backend import config
                if config.ENVIRONMENT == 'production':
                    res = UnifiedResponse({"error": "Demo login backdoor is disabled in production."}, status=403)
                    return self._inject_headers(res, req, rate_limit_info)

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

                session_store = None
                if req.env:
                    session_store = req.env.get("SESSION_STORE") if isinstance(req.env, dict) else getattr(req.env, "SESSION_STORE", None)
                if not session_store:
                    from backend import config
                    session_store = getattr(config, 'SESSION_STORE', None)
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
                    session_store = None
                    if req.env:
                        session_store = req.env.get("SESSION_STORE") if isinstance(req.env, dict) else getattr(req.env, "SESSION_STORE", None)
                    if not session_store:
                        from backend import config
                        session_store = getattr(config, 'SESSION_STORE', None)
                    await revoke_jwt_token(token, session_store=session_store)

                res = UnifiedResponse({"message": "Successfully logged out.", "authenticated": False}, status=200)
                is_prod = (config.ENVIRONMENT == 'production')
                res.set_cookie('session_token', '', expires='Thu, 01 Jan 1970 00:00:00 GMT', httponly=True, secure=is_prod, samesite='Strict')
                res.set_cookie('auth_token', '', expires='Thu, 01 Jan 1970 00:00:00 GMT', httponly=True, secure=is_prod, samesite='Strict')
                res.set_cookie('jwt_token', '', expires='Thu, 01 Jan 1970 00:00:00 GMT', httponly=True, secure=is_prod, samesite='Strict')
                return self._inject_headers(res, req, rate_limit_info)

            # 8. GET/POST /api/user/profile or /api/protected/profile
            elif parts in (['api', 'user', 'profile'], ['api', 'protected', 'profile']) and req.method in ('GET', 'POST'):
                user_id = user.get("sub") or str(user.get("id", ""))
                if not db:
                    res = UnifiedResponse({"error": "D1 Database not configured"}, status=500)
                    return self._inject_headers(res, req, rate_limit_info)

                if req.method == 'GET':
                    row = await db.prepare(
                        "SELECT id, email, name, picture, bio, skills, preferred_location, job_preferences FROM user_profiles WHERE id = ?"
                    ).bind(user_id).first()

                    if row:
                        try:
                            skills = json.loads(row.get("skills") or "[]")
                        except Exception:
                            skills = []
                        try:
                            job_preferences = json.loads(row.get("job_preferences") or "{}")
                        except Exception:
                            job_preferences = {}

                        profile = {
                            "id": row.get("id"),
                            "email": row.get("email") or "",
                            "name": row.get("name") or "",
                            "picture": row.get("picture") or "",
                            "bio": row.get("bio") or "",
                            "skills": skills,
                            "preferred_location": row.get("preferred_location") or "",
                            "job_preferences": job_preferences
                        }
                    else:
                        profile = {
                            "id": user_id,
                            "email": user.get("email", ""),
                            "name": user.get("name", ""),
                            "picture": user.get("picture", ""),
                            "bio": "",
                            "skills": [],
                            "preferred_location": "",
                            "job_preferences": {}
                        }
                        await db.prepare(
                            "INSERT INTO user_profiles (id, email, name, picture, bio, skills, preferred_location, job_preferences) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                        ).bind(
                            user_id,
                            user.get("email", ""),
                            user.get("name", ""),
                            user.get("picture", ""),
                            "",
                            json.dumps([]),
                            "",
                            json.dumps({})
                        ).run()

                    res = UnifiedResponse(profile, status=200)
                    return self._inject_headers(res, req, rate_limit_info)

                elif req.method == 'POST':
                    body_data = {}
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

                    # Fetch existing profile if present
                    row = await db.prepare(
                        "SELECT id, email, name, picture, bio, skills, preferred_location, job_preferences FROM user_profiles WHERE id = ?"
                    ).bind(user_id).first()

                    existing_profile = {}
                    if row:
                        try:
                            skills = json.loads(row.get("skills") or "[]")
                        except Exception:
                            skills = []
                        try:
                            job_preferences = json.loads(row.get("job_preferences") or "{}")
                        except Exception:
                            job_preferences = {}

                        existing_profile = {
                            "id": row.get("id"),
                            "email": row.get("email") or "",
                            "name": row.get("name") or "",
                            "picture": row.get("picture") or "",
                            "bio": row.get("bio") or "",
                            "skills": skills,
                            "preferred_location": row.get("preferred_location") or "",
                            "job_preferences": job_preferences
                        }

                    # Merge & enforce constraints
                    email = existing_profile.get("email") or user.get("email", "")
                    picture = existing_profile.get("picture") or user.get("picture", "")

                    name = body_data.get("name") if "name" in body_data else existing_profile.get("name", user.get("name", ""))
                    bio = body_data.get("bio") if "bio" in body_data else existing_profile.get("bio", "")
                    skills = body_data.get("skills") if "skills" in body_data else existing_profile.get("skills", [])
                    preferred_location = body_data.get("preferred_location") if "preferred_location" in body_data else existing_profile.get("preferred_location", "")
                    job_preferences = body_data.get("job_preferences") if "job_preferences" in body_data else existing_profile.get("job_preferences", {})

                    skills_str = json.dumps(skills)
                    job_preferences_str = json.dumps(job_preferences)

                    if row:
                        await db.prepare(
                            "UPDATE user_profiles SET email = ?, name = ?, picture = ?, bio = ?, skills = ?, preferred_location = ?, job_preferences = ? WHERE id = ?"
                        ).bind(
                            email, name, picture, bio, skills_str, preferred_location, job_preferences_str, user_id
                        ).run()
                    else:
                        await db.prepare(
                            "INSERT INTO user_profiles (id, email, name, picture, bio, skills, preferred_location, job_preferences) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                        ).bind(
                            user_id, email, name, picture, bio, skills_str, preferred_location, job_preferences_str
                        ).run()

                    updated_profile = {
                        "id": user_id,
                        "email": email,
                        "name": name,
                        "picture": picture,
                        "bio": bio,
                        "skills": skills,
                        "preferred_location": preferred_location,
                        "job_preferences": job_preferences
                    }

                    res = UnifiedResponse(updated_profile, status=200)
                    return self._inject_headers(res, req, rate_limit_info)

            # 9. GET/POST/DELETE /api/user/bookmarks or /api/protected/bookmarks
            elif parts in (['api', 'user', 'bookmarks'], ['api', 'protected', 'bookmarks']) and req.method in ('GET', 'POST', 'DELETE'):
                user_id = user.get("sub") or str(user.get("id", ""))
                if not db:
                    res = UnifiedResponse({"error": "D1 Database not configured"}, status=500)
                    return self._inject_headers(res, req, rate_limit_info)

                if req.method == 'GET':
                    result = await db.prepare(
                        "SELECT id, company_id, created_at FROM bookmarks WHERE user_id = ?"
                    ).bind(user_id).all()
                    
                    rows = result.get("results", []) if result else []
                    
                    startups = await load_all_startups()
                    startup_names = {}
                    for s in startups:
                        if "id" in s and "name" in s:
                            startup_names[str(s["id"]).strip()] = s["name"]
                    
                    bookmarks_list = []
                    for row in rows:
                        company_id = row.get("company_id")
                        saved_at = row.get("created_at")
                        
                        company_name = "Unknown"
                        comp_id_str = str(company_id).strip() if company_id is not None else ""
                        if comp_id_str in startup_names:
                            company_name = startup_names[comp_id_str]
                        else:
                            for s in startups:
                                if _ids_match(s.get("id"), company_id):
                                    company_name = s.get("name", "Unknown")
                                    break
                        
                        bookmarks_list.append({
                            "id": row.get("id"),
                            "company_id": company_id,
                            "name": company_name,
                            "saved_at": saved_at
                        })
                    
                    res = UnifiedResponse(bookmarks_list, status=200)
                    return self._inject_headers(res, req, rate_limit_info)

                elif req.method == 'POST':
                    body_data = {}
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
                    
                    company_id = body_data.get("company_id")
                    if not company_id:
                        res = UnifiedResponse({"error": "Missing company_id"}, status=400)
                        return self._inject_headers(res, req, rate_limit_info)
                    
                    res_run = await db.prepare(
                        "INSERT INTO bookmarks (user_id, company_id) VALUES (?, ?)"
                    ).bind(user_id, str(company_id)).run()
                    
                    bookmark_id = None
                    if res_run and isinstance(res_run, dict):
                        bookmark_id = res_run.get("meta", {}).get("last_row_id")
                    
                    res = UnifiedResponse({
                        "success": True,
                        "bookmark": {
                            "id": bookmark_id,
                            "company_id": company_id,
                            "user_id": user_id
                        }
                    }, status=201)
                    return self._inject_headers(res, req, rate_limit_info)

                elif req.method == 'DELETE':
                    company_id = req.query_params.get("company_id")
                    bookmark_id = req.query_params.get("bookmark_id") or req.query_params.get("id")

                    if not company_id and not bookmark_id:
                        body_data = {}
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
                        company_id = body_data.get("company_id")
                        bookmark_id = body_data.get("bookmark_id") or body_data.get("id")

                    if not company_id and not bookmark_id:
                        res = UnifiedResponse({"error": "Missing company_id or bookmark_id"}, status=400)
                        return self._inject_headers(res, req, rate_limit_info)

                    if bookmark_id:
                        await db.prepare(
                            "DELETE FROM bookmarks WHERE id = ? AND user_id = ?"
                        ).bind(bookmark_id, user_id).run()
                    else:
                        await db.prepare(
                            "DELETE FROM bookmarks WHERE company_id = ? AND user_id = ?"
                        ).bind(str(company_id), user_id).run()
                    
                    res = UnifiedResponse({"success": True, "message": "Bookmark removed"}, status=200)
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
            res = UnifiedResponse({"error": "Internal server error", "details": str(e)}, status=500)
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
