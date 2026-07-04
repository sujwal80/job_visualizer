from flask import Flask, jsonify, render_template, request, make_response, g
import json
import os
import time
import math
import gzip
import io
import re
from collections import defaultdict
from werkzeug.middleware.proxy_fix import ProxyFix

# Import modular utilities and services
from backend.utils.validators import REQUIRED_FIELDS, _sanitize_string, _safe_float, _check_has_pin, _sanitize_url, _validate_query_params, _strip_redundant
from backend.utils.rate_limiter import _rate_limits, _check_rate_limit
from backend.services.startup_service import load_startups, filter_and_sort_startups, format_startup_summary, format_startup_details

app = Flask(
    __name__, 
    static_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend', 'static'),
    template_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend', 'templates')
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

@app.after_request
def add_security_and_optimization_headers(response):
    # Mandatory CSP policy allowing OSM map tiles and CDN resources
    csp = (
        "default-src 'self' https://*.tile.openstreetmap.org https://cdnjs.cloudflare.com; "
        "script-src 'self' https://unpkg.com https://cdnjs.cloudflare.com; "
        "style-src 'self' https://fonts.googleapis.com https://unpkg.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com https://unpkg.com https://*.cartocdn.com; "
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
    
    # CORS support
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Accept, Accept-Encoding'
    
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

    # Attach Cache-Control: no-store on errors
    if response.status_code >= 400:
        response.headers['Cache-Control'] = 'no-store'
    
    # Gzip compression optimization
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
def index():
    return render_template('index.html')

@app.route('/api/startups', methods=['GET'])
def get_startups():
    client_ip = request.remote_addr or "127.0.0.1"
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
        
        filtered = filter_and_sort_startups(startups, min_lat, max_lat, min_lng, max_lng, limit, city_query, skill_query, industry_query)
        light_list = [format_startup_summary(s) for s in filtered]
            
        lean_payload = _strip_redundant(light_list)
        resp = make_response(jsonify(lean_payload))
        resp.headers['Cache-Control'] = 'public, max-age=60'
        return resp
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/startups/<int:startup_id>', methods=['GET'])
def get_startup_details(startup_id):
    client_ip = request.remote_addr or "127.0.0.1"
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

if __name__ == '__main__':
    # Servers MUST listen on localhost or 127.0.0.1 when testing. Servers MUST NOT listen on 0.0.0.0.
    app.run(debug=True, host='127.0.0.1', port=5001)
