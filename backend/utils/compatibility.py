"""
Centralized Compatibility and Platform/Environment Abstraction Layer
"""
import sys

# ==========================================
# 1. Platform-Specific Checks (e.g. fcntl)
# ==========================================
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    fcntl = None
    HAS_FCNTL = False

if HAS_FCNTL and fcntl:
    LOCK_SH = fcntl.LOCK_SH
    LOCK_EX = fcntl.LOCK_EX
    LOCK_NB = fcntl.LOCK_NB
    LOCK_UN = fcntl.LOCK_UN
else:
    LOCK_SH = 1
    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

def safe_flock(file_obj, operation):
    """Safely apply or release a file lock if fcntl is supported."""
    if HAS_FCNTL and fcntl:
        try:
            fcntl.flock(file_obj, operation)
            return True
        except Exception:
            pass
    return False

# ==========================================
# 2. Cloudflare JS Runtime Imports & Mocks
# ==========================================
try:
    from js import Response as JSResponse, Request as JSRequest, Headers as JSHeaders
    IS_WORKER = True
except ImportError:
    IS_WORKER = False

    class JSHeaders:
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
        @classmethod
        def new(cls, *args, **kwargs):
            return cls(*args, **kwargs)

    class JSResponse:
        def __init__(self, body=None, init=None, **kwargs):
            self.body = body
            self.status = 200
            headers_raw = None
            if isinstance(init, dict):
                self.status = init.get("status", 200)
                headers_raw = init.get("headers")
            elif init is not None:
                self.status = getattr(init, "status", 200)
                headers_raw = getattr(init, "headers", None)
            if "status" in kwargs:
                self.status = kwargs["status"]
            if "headers" in kwargs:
                headers_raw = kwargs["headers"]
            if isinstance(headers_raw, JSHeaders):
                self.headers = headers_raw
            else:
                self.headers = JSHeaders(headers_raw)
        @classmethod
        def new(cls, *args, **kwargs):
            return cls(*args, **kwargs)

    class JSRequest:
        def __init__(self, url, init=None, **kwargs):
            self.url = url
            self.body = None
            self.method = "GET"
            headers_raw = None
            if isinstance(init, dict):
                self.method = init.get("method", "GET")
                headers_raw = init.get("headers")
                self.body = init.get("body")
            elif init is not None:
                self.method = getattr(init, "method", "GET")
                headers_raw = getattr(init, "headers", None)
                self.body = getattr(init, "body", None)
            if "method" in kwargs:
                self.method = kwargs["method"]
            if "headers" in kwargs:
                headers_raw = kwargs["headers"]
            if "body" in kwargs:
                self.body = kwargs["body"]
            if isinstance(headers_raw, JSHeaders):
                self.headers = headers_raw
            else:
                self.headers = JSHeaders(headers_raw)
        @classmethod
        def new(cls, *args, **kwargs):
            return cls(*args, **kwargs)

# ==========================================
# 3. Environment & Testing Helpers
# ==========================================
def is_testing_environment():
    """Check if the code is currently running inside unit tests."""
    return 'unittest' in sys.modules
