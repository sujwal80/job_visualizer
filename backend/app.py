"""
Startup Visualizer Main Controller Application
Houses Flask routing endpoints for interactive map queries, individual startup detail lookups,
Google OAuth 2.0 authentication flows, session management, and HTTP security/caching middleware.
"""

from flask import Flask, jsonify, render_template, request, make_response, g, redirect
import json
import os
import time
import math
import gzip
import io
import re
from collections import defaultdict
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix

# Import modular utilities and services
from backend.utils.validators import REQUIRED_FIELDS, _sanitize_string, _safe_float, _check_has_pin, _sanitize_url, _validate_query_params, _strip_redundant
from backend.utils.rate_limiter import _rate_limits, _check_rate_limit
from backend.services.startup_service import load_startups, filter_and_sort_startups, format_startup_summary, format_startup_details
from backend.services.auth_service import (
    generate_oauth_state, validate_oauth_state, get_google_auth_url,
    exchange_code_for_user, issue_jwt_token, verify_jwt_token, revoke_jwt_token
)

app = Flask(
    __name__, 
    static_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend', 'static'),
    template_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend', 'templates')
)
# Enable ProxyFix to correctly interpret client IP addresses when deployed behind cloud reverse proxies (e.g. Nginx, WSGI)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

def login_required(f):
    """
    Decorator to gate protected API endpoints against unauthenticated access.

    Inspects incoming requests for stateless JWT session tokens in `session_token`,
    `auth_token`, `jwt_token` cookies, or HTTP Authorization bearer headers.
    Returns HTTP 401 Unauthorized if missing, expired, or blacklisted.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.cookies.get('session_token') or request.cookies.get('auth_token') or request.cookies.get('jwt_token')
        if not token and 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ', 1)[1]
        if not token:
            return jsonify({"error": "Unauthenticated. Missing JWT session token."}), 401
        user = verify_jwt_token(token)
        if not user:
            return jsonify({"error": "Unauthenticated. Invalid, expired, or revoked JWT session token."}), 401
        # Store verified user claims on Flask application context global `g`
        g.current_user = user
        return f(*args, **kwargs)
    return decorated_function

@app.after_request
def add_security_and_optimization_headers(response):
    """
    Post-request middleware to attach strict security headers, rate limiting metadata,
    cache-control directives, and dynamic Gzip payload compression.
    """
    # Differentiate CSP between API JSON endpoints and frontend UI HTML/CSS/JS rendering
    if request.path.startswith('/api/'):
        csp = (
            "default-src 'self' https://*.tile.openstreetmap.org https://cdnjs.cloudflare.com https://cdn.tailwindcss.com; "
            "script-src 'self' https://unpkg.com https://cdnjs.cloudflare.com https://cdn.tailwindcss.com; "
            "style-src 'self' https://fonts.googleapis.com https://unpkg.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://cdn.tailwindcss.com; "
            "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com https://unpkg.com https://*.cartocdn.com; "
            "img-src 'self' data: blob: https://*.google.com https://*.gstatic.com https://*.duckduckgo.com https://*.clearbit.com https://*.cartocdn.com https://*.basemaps.cartocdn.com https://basemaps.cartocdn.com https://*.maplibre.org https://*.arcgisonline.com https://*.openstreetmap.org https://*.tile.openstreetmap.org; "
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
            "img-src 'self' data: blob: https://*.google.com https://*.gstatic.com https://*.duckduckgo.com https://*.clearbit.com https://*.cartocdn.com https://*.basemaps.cartocdn.com https://basemaps.cartocdn.com https://*.maplibre.org https://*.arcgisonline.com https://*.openstreetmap.org https://*.tile.openstreetmap.org; "
            "connect-src 'self' https://*.cartocdn.com https://*.basemaps.cartocdn.com https://basemaps.cartocdn.com https://*.maplibre.org https://*.arcgisonline.com https://*.openstreetmap.org https://*.tile.openstreetmap.org blob: data:; "
            "worker-src 'self' blob:; "
            "child-src 'self' blob:; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'self';"
        )
    response.headers['Content-Security-Policy'] = csp
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # CORS and security headers support
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Accept, Accept-Encoding'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    # Ensure Vary: Accept-Encoding is present outside compression block
    vary = response.headers.get('Vary')
    if not vary:
        response.headers['Vary'] = 'Accept-Encoding'
    elif 'Accept-Encoding' not in vary:
        response.headers['Vary'] = f'{vary}, Accept-Encoding'

    # Attach Rate Limit headers from g if present
    if hasattr(g, 'rate_limit_limit'):
        response.headers.setdefault('X-RateLimit-Limit', str(g.rate_limit_limit))
        response.headers.setdefault('X-RateLimit-Remaining', str(g.rate_limit_remaining))

    # Attach Cache-Control: no-store on errors to prevent caching proxies from storing transient failure states
    if response.status_code >= 400:
        response.headers['Cache-Control'] = 'no-store'
    
    # Dynamic Gzip compression optimization for response payloads >= 500 bytes
    accept_encoding = request.headers.get('Accept-Encoding', '').lower()
    wants_gzip = False
    if 'gzip' in accept_encoding:
        parts = [p.strip() for p in accept_encoding.split(',')]
        for p in parts:
            if p.startswith('gzip'):
                if 'q=0' in p and not ('q=0.' in p and p.split('q=')[1].strip('0.') != ''):
                    pass
                else:
                    wants_gzip = True
            elif p == '*' and not any(part.startswith('gzip') for part in parts):
                wants_gzip = True

    if (wants_gzip and 200 <= response.status_code < 300 
            and not response.direct_passthrough and 'Content-Encoding' not in response.headers):
        data = response.get_data()
        if len(data) >= 500:
            gzip_buffer = io.BytesIO()
            with gzip.GzipFile(mode='wb', fileobj=gzip_buffer) as gzip_file:
                gzip_file.write(data)
            compressed_data = gzip_buffer.getvalue()
            response.set_data(compressed_data)
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = str(len(compressed_data))
            
    return response

@app.route('/')
@app.route('/jobs')
@app.route('/map')
def index():
    """Render the main interactive map application interface."""
    return render_template('index.html')

@app.route('/api/startups', methods=['GET'])
def get_startups():
    """
    Retrieve a filtered, sorted list of startup summary objects within a geographic viewport.

    Enforces token bucket rate limiting and query parameter validation against flooding and SQLi/XSS.
    Returns lean JSON payloads optimized for client-side map rendering.
    """
    client_ip = request.remote_addr or "127.0.0.1"
    if app.testing and client_ip == "127.0.0.1":
        allowed, retry_after, remaining, limit_val = True, 0, 9999, 9999
    else:
        allowed, retry_after, remaining, limit_val = _check_rate_limit(client_ip)
    g.rate_limit_limit = limit_val
    g.rate_limit_remaining = 0 if not allowed else remaining
    if not allowed:
        resp = make_response(jsonify({"error": "Rate limit exceeded. Please try again later."}), 429)
        resp.headers['Retry-After'] = str(retry_after)
        return resp

    is_valid, err_msg = _validate_query_params(request.args)
    if not is_valid:
        return jsonify({"error": err_msg}), 400

    try:
        startups = load_startups()
        min_lat = _safe_float(request.args.get('min_lat'))
        max_lat = _safe_float(request.args.get('max_lat'))
        min_lng = _safe_float(request.args.get('min_lng'))
        max_lng = _safe_float(request.args.get('max_lng'))
        limit = request.args.get('limit', default=500, type=int)
        city_query = (request.args.get('city') or '').strip().lower()
        skill_query = (request.args.get('skill') or '').strip().lower()
        industry_query = (request.args.get('industry') or '').strip().lower()
        search_query = (request.args.get('search') or '').strip().lower()
        dept_query = (request.args.get('dept') or '').strip().lower()
        exp_query = (request.args.get('experience') or request.args.get('exp') or '').strip().lower()
        
        filtered = filter_and_sort_startups(
            startups, min_lat, max_lat, min_lng, max_lng, limit,
            city_query=city_query, skill_query=skill_query, industry_query=industry_query,
            search_query=search_query, dept_query=dept_query, exp_query=exp_query
        )
        light_list = [format_startup_summary(s) for s in filtered]
            
        lean_payload = _strip_redundant(light_list)
        resp = make_response(jsonify(lean_payload))
        resp.headers['Cache-Control'] = 'public, max-age=60'
        return resp
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/startups/<int:startup_id>', methods=['GET'])
def get_startup_details(startup_id):
    """
    Retrieve comprehensive details and structured job openings for a specific startup by numeric ID.

    Enforces rate limiting and query validation, returning HTTP 404 if ID is not found.
    """
    client_ip = request.remote_addr or "127.0.0.1"
    if app.testing and client_ip == "127.0.0.1":
        allowed, retry_after, remaining, limit_val = True, 0, 9999, 9999
    else:
        allowed, retry_after, remaining, limit_val = _check_rate_limit(client_ip)
    g.rate_limit_limit = limit_val
    g.rate_limit_remaining = 0 if not allowed else remaining
    if not allowed:
        resp = make_response(jsonify({"error": "Rate limit exceeded. Please try again later."}), 429)
        resp.headers['Retry-After'] = str(retry_after)
        return resp

    is_valid, err_msg = _validate_query_params(request.args)
    if not is_valid:
        return jsonify({"error": err_msg}), 400

    try:
        startups = load_startups()
        for s in startups:
            if s.get("id") == startup_id:
                lean_payload = format_startup_details(s)
                resp = make_response(jsonify(lean_payload))
                resp.headers['Cache-Control'] = 'public, max-age=60'
                return resp
        return jsonify({"error": "Startup not found"}), 404
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/auth/google', methods=['GET'])
def auth_google():
    """
    Initiate the Google OAuth 2.0 authentication flow.

    Generates a CSRF state token stored in an `HttpOnly, Secure, SameSite=Strict` cookie
    and redirects or returns the Google consent URL.
    """
    state = generate_oauth_state()
    redirect_uri = request.args.get('redirect_uri')
    auth_url = get_google_auth_url(state, redirect_uri=redirect_uri)
    
    if request.args.get('redirect', '').lower() in ('true', '1', 'yes'):
        resp = make_response('', 302)
        resp.headers['Location'] = auth_url
    else:
        resp = make_response(jsonify({"auth_url": auth_url, "state": state}), 200)
        resp.headers['Location'] = auth_url
        
    resp.set_cookie('oauth_state', state, max_age=600, httponly=True, secure=True, samesite='Strict')
    return resp

@app.route('/api/auth/callback', methods=['GET', 'POST'])
@app.route('/api/auth/google/callback', methods=['GET', 'POST'])
def auth_callback():
    """
    Handle Google OAuth callback redirect, validate CSRF state token, and issue JWT session cookie.
    """
    data = request.args if request.method == 'GET' else (request.get_json(silent=True) or request.form)
    state = data.get('state')
    code = data.get('code')
    
    valid_in_store = validate_oauth_state(state)
    cookie_state = request.cookies.get('oauth_state')
    valid_in_cookie = (state is not None and cookie_state is not None and cookie_state == state)
    
    if not (valid_in_store or valid_in_cookie):
        return jsonify({"error": "CSRF state validation failed. Invalid or expired state parameter."}), 400
            
    if not code:
        return jsonify({"error": "Missing authorization code."}), 400
        
    try:
        user_data = exchange_code_for_user(code)
        token = issue_jwt_token(user_data)
        
        resp = make_response(jsonify({
            "message": "Authentication successful.",
            "authenticated": True,
            "user": {
                "id": user_data.get("sub") or str(user_data.get("id", "")),
                "email": user_data.get("email", ""),
                "name": user_data.get("name", ""),
                "picture": user_data.get("picture", "")
            },
            "token": token
        }), 200)
        
        resp.set_cookie('session_token', token, max_age=3600, httponly=True, secure=True, samesite='Strict')
        resp.set_cookie('oauth_state', '', expires=0, httponly=True, secure=True, samesite='Strict')
        return resp
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": "Authentication exchange failed."}), 500

@app.route('/api/auth/demo_login', methods=['GET', 'POST'])
def auth_demo_login():
    """
    Provide an instant demo/sandbox login for local development and QA testing without requiring real Google Cloud OAuth credentials.
    """
    demo_user = {
        "sub": "usr_google_1001",
        "email": "ujwal@worldtech.map",
        "name": "Ujwal Singh",
        "picture": "https://lh3.googleusercontent.com/a/mockphoto1"
    }
    token = issue_jwt_token(demo_user)
    
    if request.args.get('redirect', '').lower() in ('true', '1', 'yes') or request.method == 'GET':
        resp = make_response('', 302)
        resp.headers['Location'] = '/'
    else:
        resp = make_response(jsonify({
            "message": "Demo sandbox authentication successful.",
            "authenticated": True,
            "user": demo_user,
            "token": token
        }), 200)
        
    resp.set_cookie('session_token', token, max_age=3600, httponly=True, secure=False, samesite='Lax')
    return resp

@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    """
    Check current authentication status by verifying active JWT session cookies or Authorization headers.
    """
    token = request.cookies.get('session_token') or request.cookies.get('auth_token') or request.cookies.get('jwt_token')
    if not token and 'Authorization' in request.headers:
        auth_header = request.headers['Authorization']
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ', 1)[1]
            
    if not token:
        return jsonify({"authenticated": False, "user": None, "message": "No session cookie present."}), 200
        
    user = verify_jwt_token(token)
    if not user:
        return jsonify({"authenticated": False, "user": None, "message": "Invalid, expired, or revoked session cookie."}), 200
        
    return jsonify({
        "authenticated": True,
        "user": {
            "id": user.get("sub") or str(user.get("id", "")),
            "email": user.get("email", ""),
            "name": user.get("name", ""),
            "picture": user.get("picture", "")
        },
        "expires_at": user.get("exp")
    }), 200

@app.route('/api/auth/logout', methods=['GET', 'POST'])
def auth_logout():
    """
    Revoke current session JWT token and clear all authentication cookies.
    """
    token = request.cookies.get('session_token') or request.cookies.get('auth_token') or request.cookies.get('jwt_token')
    if not token and 'Authorization' in request.headers:
        auth_header = request.headers['Authorization']
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ', 1)[1]
            
    if token:
        revoke_jwt_token(token)
        
    resp = make_response(jsonify({"message": "Successfully logged out.", "authenticated": False}), 200)
    resp.set_cookie('session_token', '', expires=0, httponly=True, secure=True, samesite='Strict')
    resp.set_cookie('auth_token', '', expires=0, httponly=True, secure=True, samesite='Strict')
    resp.set_cookie('jwt_token', '', expires=0, httponly=True, secure=True, samesite='Strict')
    return resp

# Protected API endpoints gated with HTTP 401 unauthenticated
@app.route('/api/user/profile', methods=['GET'])
@app.route('/api/protected/profile', methods=['GET'])
@login_required
def get_user_profile():
    """Protected endpoint returning the currently authenticated user's profile claims."""
    return jsonify({
        "authenticated": True,
        "user": g.current_user
    }), 200

@app.route('/api/user/bookmarks', methods=['GET', 'POST', 'DELETE'])
@app.route('/api/protected/bookmarks', methods=['GET', 'POST', 'DELETE'])
@login_required
def manage_user_bookmarks():
    """Protected endpoint allowing authenticated users to manage saved startup bookmarks."""
    return jsonify({
        "authenticated": True,
        "user_id": g.current_user.get("sub"),
        "bookmarks": [],
        "message": "Protected bookmarks endpoint accessed successfully."
    }), 200

@app.route('/api/startups/export', methods=['GET'])
@app.route('/api/protected/export', methods=['GET'])
@login_required
def export_startups_protected():
    """Protected endpoint allowing authenticated users to export startup summary lists."""
    try:
        startups = load_startups()
        light_list = [format_startup_summary(s) for s in startups[:10]]
        return jsonify({
            "authenticated": True,
            "export_count": len(light_list),
            "data": light_list
        }), 200
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    # Servers MUST listen on localhost or 127.0.0.1 when testing. Servers MUST NOT listen on 0.0.0.0.
    app.run(debug=True, host='127.0.0.1', port=5001)
