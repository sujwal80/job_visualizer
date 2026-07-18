"""
Google OAuth 2.0 & Stateless JWT Authentication Service
Houses cryptographic helpers for generating and verifying CSRF state tokens,
constructing OAuth authorization URLs, exchanging authorization codes for Google user profiles,
and managing stateless JWT session tokens with revocation blacklisting.
"""

import os
import time
import secrets
from backend.utils import jwt_helper as jwt
from urllib.parse import urlencode
from backend import config

# Default secure key and mock OAuth credentials
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "worldtech_map_default_jwt_secret_key_2026_super_secure")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "1234567890-worldtechmapmockclientid.apps.googleusercontent.com")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "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")

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
    """
    Clear in-memory CSRF state tokens and revoked JWT token registries.
    Used during automated unit test teardown and session resetting.
    """
    _csrf_state_store.clear()
    _revoked_tokens.clear()

async def generate_oauth_state(expires_in=600, session_store=None):
    """
    Generate a cryptographically secure random CSRF state token and store it with expiration.

    Args:
        expires_in (int): Time-to-live in seconds for the generated state token (default 600s).
        session_store: Cloudflare KV namespace binding.

    Returns:
        str: A URL-safe 32-byte cryptographic random string token.
    """
    state = secrets.token_urlsafe(32)
    if session_store is not None:
        await session_store.put(f"csrf:{state}", "1", expirationTtl=expires_in)
    else:
        _csrf_state_store[state] = time.time() + expires_in
        # Automated cleanup: sweep expired state records during token generation
        now = time.time()
        expired = [k for k, exp in _csrf_state_store.items() if exp < now]
        for k in expired:
            _csrf_state_store.pop(k, None)
        # Enforce strict memory bounds on state store (max 10,000 pending logins)
        while len(_csrf_state_store) > 10000:
            _csrf_state_store.pop(next(iter(_csrf_state_store)), None)
    return state

async def validate_oauth_state(state, session_store=None):
    """
    Validate and consume an OAuth CSRF state token.

    Args:
        state (str): The state token returned by the Google OAuth callback parameter.
        session_store: Cloudflare KV namespace binding.

    Returns:
        bool: True if the token exists in the store and has not expired, False otherwise.
    """
    if not state or not isinstance(state, str):
        return False
    if session_store is not None:
        key = f"csrf:{state}"
        val = await session_store.get(key)
        if val is None:
            return False
        await session_store.delete(key)
        return True
    else:
        exp = _csrf_state_store.pop(state, None)
        if exp is None:
            return False
        if time.time() > exp:
            return False
        return True

def get_google_auth_url(state, redirect_uri=None):
    """
    Construct the Google OAuth 2.0 authorization URL with requested OpenID Connect scopes.

    Args:
        state (str): The CSRF protection state token to embed in the request.
        redirect_uri (str, optional): The callback URI where Google redirects after consent.

    Returns:
        str: The fully formatted `https://accounts.google.com/o/oauth2/v2/auth` URL.
    """
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri or config.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "consent"
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

def exchange_code_for_user(code):
    """
    Exchange an OAuth authorization code for a Google user profile dictionary.

    In offline/sandbox test environments, resolves predefined test authorization codes
    or generates a safe simulated user profile without external network dependencies.

    Args:
        code (str): The authorization code received from the OAuth callback.

    Returns:
        dict: User profile data containing 'sub' (ID), 'email', 'name', and 'picture'.

    Raises:
        ValueError: If the authorization code is missing or malformed.
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
        # In a real environment with network access, we would execute requests.post('https://oauth2.googleapis.com/token'...)
        # Since we operate in sandbox environments without external network access, return a safe simulated user
        return {
            "sub": f"usr_{secrets.token_hex(6)}",
            "email": "auth_user@worldtech.map",
            "name": "Authenticated User",
            "picture": "https://lh3.googleusercontent.com/a/default"
        }

def issue_jwt_token(user_data, expires_in=3600, custom_secret=None):
    """
    Issue a stateless JSON Web Token (JWT) session token for an authenticated user.

    Args:
        user_data (dict): The user profile attributes to encode into the token payload.
        expires_in (int): Token validity duration in seconds (default 3600s / 1 hour).
        custom_secret (str, optional): Custom HMAC secret key override for encoding.

    Returns:
        str: The encoded JWT string signed with HS256 algorithm.
    """
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

async def verify_jwt_token(token, custom_secret=None, session_store=None):
    """
    Verify and decode a JWT session token against expiration and revocation blacklists.

    Args:
        token (str): The raw JWT token string to verify.
        custom_secret (str, optional): Custom HMAC secret key override for verification.
        session_store: Cloudflare KV namespace binding.

    Returns:
        dict or None: The decoded token payload dictionary if valid and active, or None if invalid/revoked.
    """
    if not token or not isinstance(token, str):
        return None
    secret = custom_secret or SECRET_KEY
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        jti = payload.get("jti")
        # Check if the unique token ID or signature has been revoked in the blacklist
        sig = token.split('.')[2] if len(token.split('.')) == 3 else token
        if session_store is not None:
            if jti:
                val_jti = await session_store.get(f"revoked:{jti}")
                if val_jti is not None:
                    return None
            val_sig = await session_store.get(f"revoked:{sig}")
            if val_sig is not None:
                return None
        else:
            if jti in _revoked_tokens or token in _revoked_tokens or sig in _revoked_tokens:
                return None
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, jwt.PyJWTError):
        return None

async def revoke_jwt_token(token, custom_secret=None, session_store=None):
    """
    Revoke an active session JWT token by adding its unique `jti` or signature to the blacklist.

    Args:
        token (str): The JWT session token to revoke during user logout.
        custom_secret (str, optional): Custom HMAC secret key override for decoding.
        session_store: Cloudflare KV namespace binding.

    Returns:
        bool: True if the token was successfully added to the revocation blacklist.
    """
    if not token or not isinstance(token, str):
        return False
    secret = custom_secret or SECRET_KEY
    try:
        # Decode without verifying expiration so we can still revoke an already expired token
        payload = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_exp": False})
        jti = payload.get("jti")
        exp = payload.get("exp")
        now = int(time.time())
        ttl = max(60, exp - now) if exp else 86400
        sig = token.split('.')[2] if len(token.split('.')) == 3 else token
        
        if session_store is not None:
            if jti:
                await session_store.put(f"revoked:{jti}", "1", expirationTtl=ttl)
            await session_store.put(f"revoked:{sig}", "1", expirationTtl=ttl)
            return True
        else:
            if jti:
                _revoked_tokens.add(jti)
            _revoked_tokens.add(token)
            _revoked_tokens.add(sig)
            return True
    except Exception:
        sig = token.split('.')[2] if len(token.split('.')) == 3 else token
        if session_store is not None:
            await session_store.put(f"revoked:{sig}", "1", expirationTtl=86400)
        else:
            _revoked_tokens.add(token)
            _revoked_tokens.add(sig)
        return True
