"""
Simple HS256 JWT Implementation to avoid PyJWT dependency in Cloudflare Workers.
"""

import base64
import hmac
import hashlib
import json
import time

def base64url_encode(payload):
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    elif isinstance(payload, dict):
        payload = json.dumps(payload).encode('utf-8')
    return base64.urlsafe_b64encode(payload).replace(b'=', b'').decode('utf-8')

def base64url_decode(payload):
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    rem = len(payload) % 4
    if rem > 0:
        payload += b'=' * (4 - rem)
    return base64.urlsafe_b64decode(payload)

class JWTError(Exception):
    pass

class PyJWTError(JWTError):
    pass

class ExpiredSignatureError(PyJWTError):
    pass

class InvalidTokenError(PyJWTError):
    pass


def encode(payload, secret, algorithm="HS256"):
    if algorithm != "HS256":
        raise ValueError("Only HS256 is supported")
    header = {"alg": "HS256", "typ": "JWT"}
    
    segments = []
    segments.append(base64url_encode(header))
    segments.append(base64url_encode(payload))
    
    signing_input = ".".join(segments).encode('utf-8')
    key = secret.encode('utf-8')
    signature = hmac.new(key, signing_input, hashlib.sha256).digest()
    
    segments.append(base64url_encode(signature))
    return ".".join(segments)

def decode(jwt_str, secret, algorithms=["HS256"], options=None):
    if "HS256" not in algorithms:
        raise ValueError("Only HS256 is supported")
    
    options = options or {}
    verify_exp = options.get("verify_exp", True)
    
    try:
        if isinstance(jwt_str, bytes):
            jwt_str = jwt_str.decode('utf-8')
        parts = jwt_str.split('.')
        if len(parts) != 3:
            raise InvalidTokenError("Invalid token segments")
        
        header_segment, payload_segment, crypto_segment = parts
        
        # Verify signature
        signing_input = (header_segment + "." + payload_segment).encode('utf-8')
        key = secret.encode('utf-8')
        signature = base64url_decode(crypto_segment)
        
        expected_signature = hmac.new(key, signing_input, hashlib.sha256).digest()
        
        if not hmac.compare_digest(signature, expected_signature):
            raise InvalidTokenError("Signature verification failed")
            
        payload = json.loads(base64url_decode(payload_segment).decode('utf-8'))
        
        if verify_exp and 'exp' in payload:
            if time.time() > payload['exp']:
                raise ExpiredSignatureError("Token expired")
                
        return payload
    except Exception as e:
        if isinstance(e, (ExpiredSignatureError, InvalidTokenError)):
            raise e
        raise InvalidTokenError(str(e))
