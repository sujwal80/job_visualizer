import { setupConfig } from './config.js';
import { UnifiedRequest, UnifiedRouter } from './unified_router.js';

const router = new UnifiedRouter();

export default {
  async fetch(request, env, ctx) {
    try {
      setupConfig(env);
      return await handleFetch(request, env);
    } catch (e) {
      return new Response(`Internal Server Error: ${e.message}`, { status: 500 });
    }
  }
};

async function handleFetch(request, env) {
  const url = new URL(request.url);
  const path = url.pathname;
  const method = request.method.toUpperCase();

  if (method === "OPTIONS") {
    return new Response("", {
      status: 204,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization, Accept, Accept-Encoding',
        'Access-Control-Max-Age': '86400'
      }
    });
  }

  if (!path.startsWith('/api/')) {
    if (['/', '/jobs', '/map'].includes(path)) {
      const newUrl = new URL('/index.html', request.url);
      const assetRequest = new Request(newUrl.toString(), {
        method: request.method,
        headers: request.headers
      });
      const assetResponse = await env.ASSETS.fetch(assetRequest);
      return injectAssetHeaders(assetResponse, path);
    } else {
      const assetResponse = await env.ASSETS.fetch(request);
      return injectAssetHeaders(assetResponse, path);
    }
  }

  let body = null;
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    try {
      body = await request.text();
    } catch (e) {
      body = "";
    }
  }

  const testingMode = env.ENVIRONMENT === 'test' || (env.SESSION_STORE && env.SESSION_STORE.constructor.name === 'MockKVStore');

  const unifiedReq = new UnifiedRequest({
    method,
    path,
    url: request.url,
    headers: request.headers,
    queryParams: url.searchParams,
    body,
    testing: testingMode,
    env
  });

  const unifiedRes = await router.handleRequest(unifiedReq);

  const jsHeaders = new Headers();
  for (const [k, v] of Object.entries(unifiedRes.headers)) {
    if (k.toLowerCase() === 'set-cookie') continue;
    jsHeaders.set(k, v);
  }

  for (const cookie of unifiedRes.cookies) {
    const parts = [`${cookie.name}=${cookie.value}`];
    if (cookie.max_age !== undefined) parts.push(`Max-Age=${cookie.max_age}`);
    if (cookie.expires !== undefined) parts.push(`Expires=${cookie.expires}`);
    if (cookie.path) parts.push(`Path=${cookie.path}`);
    if (cookie.httponly) parts.push("HttpOnly");
    if (cookie.secure) parts.push("Secure");
    if (cookie.samesite) parts.push(`SameSite=${cookie.samesite}`);
    
    jsHeaders.append('Set-Cookie', parts.join('; '));
  }

  let resBody = unifiedRes.body;
  if (resBody !== null && typeof resBody === 'object') {
    resBody = JSON.stringify(resBody);
  } else if (resBody === null || resBody === undefined) {
    resBody = "";
  } else {
    resBody = String(resBody);
  }

  return new Response(resBody, {
    status: unifiedRes.status,
    headers: jsHeaders
  });
}

function injectAssetHeaders(response, path) {
  const headersObj = {};
  for (const [k, v] of response.headers.entries()) {
    headersObj[k] = v;
  }
  
  const enrichedHeaders = UnifiedRouter.injectSecurityHeaders(headersObj, path);
  
  if (response.status >= 400) {
    enrichedHeaders['cache-control'] = 'no-store';
  }
  
  const newHeaders = new Headers();
  for (const [k, v] of Object.entries(enrichedHeaders)) {
    if (k.toLowerCase() === 'set-cookie') continue;
    newHeaders.set(k, v);
  }
  
  const setCookies = response.headers.getSetCookie ? response.headers.getSetCookie() : [];
  setCookies.forEach(cookie => newHeaders.append('Set-Cookie', cookie));

  return new Response(response.body, {
    status: response.status,
    headers: newHeaders
  });
}
