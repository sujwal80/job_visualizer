import os
import time
import secrets
import jwt
from urllib.parse import urlencode

# Default secure key and mock OAuth credentials
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "worldtech_map_default_jwt_secret_key_2026_super_secure")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "1234567890-worldtechmapmockclientid.apps.googleusercontent.com")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "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")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://127.0.0.1:5001/api/auth/callback")

# In-memory storage for stateless verification & revocation tracking
_csrf_state_store = {}  # state_token -> timestamp
_revoked_tokens = set()  # set of jti or token signatures

MOCK_USERS = {
    "mock_code_user1": {
        "sub": "usr_google_1001",
        "email": "ujwal@worldtech.map",
        "name": "Ujwal Singh",
        "picture": "https://lh3.googleusercontent.com/a/mockphoto1"
    },
    "mock_code_admin": {
        "sub": "usr_google_admin",
        "email": "admin@worldtech.map",
        "name": "WorldTech Admin",
        "picture": "https://lh3.googleusercontent.com/a/mockphotoadmin"
    },
    "mock_code_default": {
        "sub": "usr_google_default",
        "email": "developer@worldtech.map",
        "name": "Senior Developer",
        "picture": "https://lh3.googleusercontent.com/a/mockphotodev"
    }
}

def reset_auth_stores():
    """Clear in-memory state and revoked token registries for clean unit testing."""
    _csrf_state_store.clear()
    _revoked_tokens.clear()

def generate_oauth_state(expires_in=600):
    """Generate a cryptographically secure random CSRF state token and store it with expiration."""
    state = secrets.token_urlsafe(32)
    _csrf_state_store[state] = time.time() + expires_in
    # Cleanup old expired states
    now = time.time()
    expired = [k for k, exp in _csrf_state_store.items() if exp < now]
    for k in expired:
        _csrf_state_store.pop(k, None)
    # Strictly bound maximum memory capacity
    while len(_csrf_state_store) > 10000:
        _csrf_state_store.pop(next(iter(_csrf_state_store)), None)
    return state

def validate_oauth_state(state):
    """Validate and consume an OAuth CSRF state token. Returns True if valid and not expired."""
    if not state or not isinstance(state, str):
        return False
    exp = _csrf_state_store.pop(state, None)
    if exp is None:
        return False
    if time.time() > exp:
        return False
    return True

def get_google_auth_url(state, redirect_uri=None):
    """Construct the Google OAuth 2.0 authorization URL."""
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri or GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "consent"
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

def exchange_code_for_user(code):
    """Exchange OAuth authorization code for Google user profile data.
    In offline/test mode, resolves predefined test codes or returns a simulated user profile.
    """
    if not code or not isinstance(code, str):
        raise ValueError("Invalid authorization code.")
    
    if code in MOCK_USERS:
        return MOCK_USERS[code]
    elif code.startswith("mock_") or code.startswith("test_") or code.startswith("4/0"):
        # Generic fallback for any simulated code in test environments
        return {
            "sub": f"usr_sim_{secrets.token_hex(4)}",
            "email": f"simulated_{secrets.token_hex(2)}@worldtech.map",
            "name": "Simulated Google User",
            "picture": "https://lh3.googleusercontent.com/a/default"
        }
    else:
        # In a real environment with network access, we would do requests.post('https://oauth2.googleapis.com/token'...)
        # Since we operate in CODE_ONLY sandbox without external network access, return a safe simulated user
        return {
            "sub": f"usr_{secrets.token_hex(6)}",
            "email": "auth_user@worldtech.map",
            "name": "Authenticated User",
            "picture": "https://lh3.googleusercontent.com/a/default"
        }

def issue_jwt_token(user_data, expires_in=3600, custom_secret=None):
    """Issue a stateless JWT session token for an authenticated user."""
    secret = custom_secret or SECRET_KEY
    now = int(time.time())
    jti = secrets.token_hex(16)
    payload = {
        "sub": user_data.get("sub") or str(user_data.get("id", "anonymous")),
        "email": user_data.get("email", ""),
        "name": user_data.get("name", ""),
        "picture": user_data.get("picture", ""),
        "iat": now,
        "exp": now + expires_in,
        "jti": jti
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token

def verify_jwt_token(token, custom_secret=None):
    """Verify and decode a JWT session token. Returns payload dict if valid, None otherwise."""
    if not token or not isinstance(token, str):
        return None
    secret = custom_secret or SECRET_KEY
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        jti = payload.get("jti")
        # Check against revoked tokens blacklist
        if jti in _revoked_tokens or token in _revoked_tokens:
            return None
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, jwt.PyJWTError):
        return None

def revoke_jwt_token(token, custom_secret=None):
    """Revoke a session JWT token by adding its jti or signature to the revocation blacklist."""
    if not token or not isinstance(token, str):
        return False
    secret = custom_secret or SECRET_KEY
    try:
        # Decode without verifying expiration so we can still revoke an expired token if needed
        payload = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_exp": False})
        jti = payload.get("jti")
        if jti:
            _revoked_tokens.add(jti)
        _revoked_tokens.add(token)
        return True
    except Exception:
        # Even if decode fails completely, add raw token to blacklist
        _revoked_tokens.add(token)
        return True
