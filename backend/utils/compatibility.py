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
    import pyodide
    import js as js_module
    IS_WORKER = True

    def create_response(body, status, headers):
        init_dict = {
            "status": status,
            "headers": headers
        }
        js_init = pyodide.ffi.to_js(init_dict, dict_converter=js_module.Object.fromEntries)
        return JSResponse.new(body, js_init)
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

    def create_response(body, status, headers):
        init = {
            "status": status,
            "headers": headers
        }
        return JSResponse.new(body, init)

# ==========================================
# 2.5 Cross-Platform Async HTTP Client
# ==========================================
import json

async def fetch_json(url, method="GET", headers=None, body=None):
    """
    Cross-platform asynchronous HTTP client helper to fetch JSON resources.
    
    If IS_WORKER is True, it uses native js.fetch.
    If IS_WORKER is False, it uses urllib.request in a thread.
    """
    if body is not None and not isinstance(body, (str, bytes)):
        body = json.dumps(body)

    if IS_WORKER:
        import js as js_module
        import pyodide
        
        js_headers = pyodide.ffi.to_js(headers or {}, dict_converter=js_module.Object.fromEntries)
        init_dict = {
            "method": method,
            "headers": js_headers,
        }
        if body is not None:
            init_dict["body"] = body
        js_init = pyodide.ffi.to_js(init_dict, dict_converter=js_module.Object.fromEntries)
        
        response = await js_module.fetch(url, js_init)
        text = await response.text()
        return json.loads(text)
    else:
        import urllib.request
        
        def _fetch_sync():
            req = urllib.request.Request(url, method=method)
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
            data = body.encode('utf-8') if isinstance(body, str) else body
            with urllib.request.urlopen(req, data=data) as response:
                resp_bytes = response.read()
                return json.loads(resp_bytes.decode('utf-8'))
                
        return await asyncio.to_thread(_fetch_sync)

# ==========================================
# 3. Environment & Testing Helpers
# ==========================================
def is_testing_environment():
    """Check if the code is currently running inside unit tests."""
    return 'unittest' in sys.modules


# ==========================================
# 4. SQLite Key-Value Store Implementation
# ==========================================
import sqlite3
import os
import time
import asyncio

class SQLiteKVStore:
    """SQLite-backed Key-Value Store supporting async put, get, and delete operations."""
    def __init__(self, db_path="tmp/local_kv.db"):
        self.db_path = db_path
        # Ensure target folder exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        # Initialize table structures
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS kv_store (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        expires_at REAL
                    )
                """)
        finally:
            conn.close()

    def _get_sync(self, key):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value, expires_at FROM kv_store WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                val, expires_at = row
                if expires_at is not None and time.time() > expires_at:
                    cursor.execute("DELETE FROM kv_store WHERE key = ?", (key,))
                    conn.commit()
                    return None
                return val
            return None
        finally:
            conn.close()

    def _put_sync(self, key, value, expires_at=None):
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO kv_store (key, value, expires_at) VALUES (?, ?, ?)",
                    (key, str(value), expires_at)
                )
        finally:
            conn.close()

    def _delete_sync(self, key):
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                conn.execute("DELETE FROM kv_store WHERE key = ?", (key,))
        finally:
            conn.close()

    async def get(self, key):
        return await asyncio.to_thread(self._get_sync, key)

    async def put(self, key, value, expirationTtl=None):
        expires_at = time.time() + expirationTtl if expirationTtl is not None else None
        await asyncio.to_thread(self._put_sync, key, value, expires_at)

    async def delete(self, key):
        await asyncio.to_thread(self._delete_sync, key)


class SQLiteD1PreparedStatement:
    def __init__(self, db, query, params=None):
        self.db = db
        self.query = query
        self.params = params or []

    def bind(self, *args):
        if len(args) == 1 and isinstance(args[0], (list, tuple, dict)):
            params = args[0]
        else:
            params = args
        return SQLiteD1PreparedStatement(self.db, self.query, params)

    async def run(self):
        def _execute():
            conn = sqlite3.connect(self.db.db_path)
            conn.row_factory = sqlite3.Row
            try:
                with conn:
                    cursor = conn.execute(self.query, self.params)
                    rows = cursor.fetchall()
                    results = [dict(row) for row in rows]
                    return {
                        "success": True,
                        "results": results,
                        "meta": {
                            "changes": conn.total_changes,
                            "duration": 0,
                            "last_row_id": cursor.lastrowid
                        }
                    }
            except Exception as e:
                import traceback, sys
                print(f"[SQLite Error] {e}", file=sys.stderr)
                traceback.print_exc()
                return {
                    "success": False,
                    "error": str(e),
                    "results": []
                }
            finally:
                conn.close()
        return await asyncio.to_thread(_execute)

    async def all(self):
        res = await self.run()
        class D1Result:
            def __init__(self, results, success=True):
                self.results = results
                self.success = success
            def __getitem__(self, key):
                if key == "results":
                    return self.results
                raise KeyError(key)
            def get(self, key, default=None):
                if key == "results":
                    return self.results
                return default
        return D1Result(res.get("results", []), success=res.get("success", False))

    async def first(self, col_name=None):
        res = await self.run()
        results = res.get("results", [])
        if not results:
            return None
        row = results[0]
        if col_name is not None:
            return row.get(col_name)
        return row


class SQLiteD1Database:
    def __init__(self, db_path="tmp/local_d1.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_profiles (
                        id TEXT PRIMARY KEY,
                        email TEXT,
                        name TEXT,
                        picture TEXT,
                        bio TEXT,
                        skills TEXT,
                        preferred_location TEXT,
                        job_preferences TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS bookmarks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT,
                        company_id TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
        finally:
            conn.close()

    def prepare(self, query):
        return SQLiteD1PreparedStatement(self, query)

    async def exec(self, query):
        def _execute():
            conn = sqlite3.connect(self.db_path)
            try:
                with conn:
                    conn.executescript(query)
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
            finally:
                conn.close()
        return await asyncio.to_thread(_execute)

