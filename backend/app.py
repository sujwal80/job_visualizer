"""
Startup Visualizer Main Controller Application
Houses Flask routing endpoints for interactive map queries, individual startup detail lookups,
Google OAuth 2.0 authentication flows, session management, and HTTP security/caching middleware.
"""

from flask import Flask, jsonify, render_template, request, make_response
import os
import gzip
import io
from werkzeug.middleware.proxy_fix import ProxyFix

from backend import config
import asyncio
from backend.unified_router import UnifiedRequest, UnifiedRouter


def get_session_store():
    """Retrieve session_store from Flask request context or config globals."""
    try:
        if 'SESSION_STORE' in request.environ:
            return request.environ['SESSION_STORE']
        if 'env' in request.environ:
            env = request.environ['env']
            if hasattr(env, 'SESSION_STORE'):
                return env.SESSION_STORE
            if isinstance(env, dict) and 'SESSION_STORE' in env:
                return env['SESSION_STORE']
    except Exception:
        pass
    try:
        return config.SESSION_STORE
    except AttributeError:
        return None

app = Flask(
    __name__, 
    static_folder=os.path.join(os.path.dirname(__file__), '..', 'public', 'static'),
    template_folder=os.path.join(os.path.dirname(__file__), '..', 'public')
)
# Enable ProxyFix to correctly interpret client IP addresses when deployed behind cloud reverse proxies (e.g. Nginx, WSGI)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
router = UnifiedRouter()

@app.after_request
def add_security_and_optimization_headers(response):
    """
    Post-request middleware to attach strict security headers, rate limiting metadata,
    cache-control directives, and dynamic Gzip payload compression.
    """
    if not request.path.startswith('/api/'):
        injected = UnifiedRouter.inject_security_headers(dict(response.headers), request.path)
        for k, v in injected.items():
            response.headers[k] = v

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

@app.route('/api/', methods=['GET', 'POST', 'DELETE', 'OPTIONS'])
@app.route('/api/<path:path>', methods=['GET', 'POST', 'DELETE', 'OPTIONS'])
def api_gateway(path=""):
    body = None
    if request.method == 'POST':
        body = request.get_json(silent=True) or request.form.to_dict() or request.get_data()

    env = {
        'SESSION_STORE': get_session_store()
    }

    req = UnifiedRequest(
        method=request.method,
        path=request.path,
        url=request.url,
        headers=dict(request.headers),
        query_params=request.args.to_dict(flat=False),
        body=body,
        cookies=request.cookies,
        testing=app.testing,
        env=env,
        client_ip=request.remote_addr
    )

    unified_resp = asyncio.run(router.handle_request(req))

    if isinstance(unified_resp.body, dict) or isinstance(unified_resp.body, list):
        flask_resp = make_response(jsonify(unified_resp.body), unified_resp.status)
    else:
        flask_resp = make_response(unified_resp.body or "", unified_resp.status)

    for k, v in unified_resp.headers.items():
        flask_resp.headers[k] = v

    for cookie in unified_resp.cookies:
        flask_resp.set_cookie(
            key=cookie['name'],
            value=cookie['value'],
            max_age=cookie.get('max_age'),
            expires=cookie.get('expires'),
            path=cookie.get('path', '/'),
            secure=cookie.get('secure', False),
            httponly=cookie.get('httponly', False),
            samesite=cookie.get('samesite')
        )

    return flask_resp


if __name__ == '__main__':
    # Servers MUST listen on localhost or 127.0.0.1 when testing. Servers MUST NOT listen on 0.0.0.0.
    app.run(debug=True, host='127.0.0.1', port=5001)
