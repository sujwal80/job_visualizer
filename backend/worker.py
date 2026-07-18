"""
Cloudflare Workers Entrypoint Application
Implements WorkerEntrypoint to route API endpoints, handle OAuth callbacks,
session KV verification, and static asset delivery via the ASSETS binding.
"""

import json
import sys
from http.cookies import SimpleCookie


from urllib.parse import urlparse, parse_qs, urlunparse
from backend.config import setup_config
from backend.services.startup_service import get_data_version
from backend.unified_router import UnifiedRequest, UnifiedRouter


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
        self.router = UnifiedRouter()


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

        # Parse query parameters using parse_qs(urlparse(request.url).query)
        query_params = parse_qs(parsed_url.query)

        # Parse request headers
        req_headers = {}
        if hasattr(request.headers, "entries"):
            try:
                for k, v in request.headers.entries():
                    req_headers[k.lower()] = v
            except Exception:
                pass
        if not req_headers and hasattr(request.headers, "_headers"):
            req_headers = {k: v for k, v in request.headers._headers}
        elif not req_headers:
            try:
                for k, v in request.headers.items():
                    req_headers[k.lower()] = v
            except Exception:
                pass

        # Parse request body
        body = None
        if method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            if hasattr(request, "text"):
                try:
                    body = await request.text()
                except Exception:
                    body = ""
            else:
                body = getattr(request, "body", "")
            if hasattr(body, "decode"):
                body = body.decode("utf-8")

        # Determine if running in testing mode
        testing_mode = False
        if 'unittest' in sys.modules:
            testing_mode = True
        elif hasattr(self.env, "SESSION_STORE") and self.env.SESSION_STORE.__class__.__name__ == "MockKVStore":
            testing_mode = True

        # Construct a UnifiedRequest
        unified_req = UnifiedRequest(
            method=method,
            path=path,
            url=request.url,
            headers=req_headers,
            query_params=query_params,
            body=body,
            cookies=None,
            testing=testing_mode,
            env=self.env
        )

        # Execute UnifiedRouter
        unified_res = await self.router.handle_request(unified_req)

        # Convert UnifiedResponse to Cloudflare Response
        try:
            from js import Headers as JSHeaders, Response as JSResponse
        except ImportError:
            JSHeaders = Headers
            JSResponse = Response

        js_headers = JSHeaders()
        for k, v in unified_res.headers.items():
            if k.lower() == 'set-cookie':
                pass
            else:
                js_headers.set(k, v)

        # Set cookies
        for cookie in unified_res.cookies:
            cookie_parts = [f"{cookie['name']}={cookie['value']}"]
            if cookie.get('max_age') is not None:
                cookie_parts.append(f"Max-Age={cookie['max_age']}")
            if cookie.get('expires') is not None:
                cookie_parts.append(f"Expires={cookie['expires']}")
            if cookie.get('path'):
                cookie_parts.append(f"Path={cookie['path']}")
            if cookie.get('httponly'):
                cookie_parts.append("HttpOnly")
            if cookie.get('secure'):
                cookie_parts.append("Secure")
            if cookie.get('samesite'):
                cookie_parts.append(f"SameSite={cookie['samesite']}")
            
            cookie_str = "; ".join(cookie_parts)
            js_headers.append('Set-Cookie', cookie_str)

        # Serialize body if necessary
        res_body = unified_res.body
        if isinstance(res_body, (dict, list)):
            res_body = json.dumps(res_body)
        elif res_body is None:
            res_body = ""
        else:
            res_body = str(res_body)

        return JSResponse(res_body, status=unified_res.status, headers=js_headers)


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

        headers_dict = UnifiedRouter.inject_security_headers(headers_dict, path)

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
