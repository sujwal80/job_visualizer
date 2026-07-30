import { test, expect } from '@playwright/test';

test.describe('Production Audit E2E (API)', () => {

  test('01 security headers', async ({ request }) => {
    const response = await request.get('/api/companies');
    expect(response.ok()).toBe(true);
    
    const headers = response.headers();
    expect(headers['content-security-policy']).toBeDefined();
    expect(headers['x-content-type-options']).toBe('nosniff');
    expect(headers['x-frame-options']).toBe('SAMEORIGIN');
  });

  test('02 rate limiting 429', async ({ request }) => {
    const testIp = '10.0.0.88'; // Isolated IP
    let rateLimited = false;
    let lastResponse;

    // Send requests in a loop to trigger rate limit
    for (let i = 0; i < 150; i++) {
      lastResponse = await request.get('/api/companies', {
        headers: { 'CF-Connecting-IP': testIp }
      });
      if (lastResponse.status() === 429) {
        rateLimited = true;
        break;
      }
    }

    expect(rateLimited).toBe(true);
    const body = await lastResponse.json();
    expect(body.error).toBeDefined();
    
    const headers = lastResponse.headers();
    expect(headers['retry-after']).toBeDefined();
    expect(headers['x-ratelimit-remaining']).toBe('0');
  });

  test('03 query param sanitization 400', async ({ request }) => {
    const payloads = [
      '/api/companies?min_lat=invalid_float&limit=abc',
      '/api/companies?min_lat=-999&max_lat=999',
      '/api/companies?city=<script>alert("XSS")</script>',
      '/api/companies?limit=-50',
      '/api/companies?city=Bengaluru\' OR \'1\'=\'1'
    ];
    
    for (const url of payloads) {
      const resp = await request.get(url);
      expect(resp.status()).not.toBe(500);
      expect([200, 400]).toContain(resp.status());
      if (resp.status() === 200) {
        const data = await resp.json();
        expect(Array.isArray(data)).toBe(true);
      }
    }
  });

  test('04 response optimization and caching', async ({ request }) => {
    const resp = await request.get('/api/companies');
    expect(resp.status()).toBe(200);
    
    const headers = resp.headers();
    expect(headers['cache-control']).toContain('public, max-age=60');
    
    const data = await resp.json();
    if (data.length > 0) {
      const item = data[0];
      expect(item.id).toBeDefined();
      expect(item.name).toBeDefined();
      expect(item.lat).toBeDefined();
      expect(item.lng).toBeDefined();
      expect(item.city).toBeDefined();
      expect(item.job_openings).toBeUndefined(); // verify pruned
    }
  });

  test('03b adversarial nan inf floats', async ({ request }) => {
    const adversarialFloats = [
      '/api/companies?min_lat=nan',
      '/api/companies?max_lat=inf',
      '/api/companies?min_lng=-inf',
      '/api/companies?max_lng=1e308'
    ];
    for (const url of adversarialFloats) {
      const resp = await request.get(url);
      expect(resp.status()).toBe(400);
    }
  });

  test('03c multidict duplicate param collisions', async ({ request }) => {
    const duplicateUrls = [
      '/api/companies?limit=10&limit=abc',
      '/api/companies?min_lat=12.97&min_lat=invalid',
      '/api/companies?limit=-10&limit=20'
    ];
    for (const url of duplicateUrls) {
      const resp = await request.get(url);
      expect(resp.status()).toBe(400);
    }
  });

  test('03d parameter flooding and long strings', async ({ request }) => {
    const floodingUrls = [
      '/api/companies?city=' + ('A' * 101),
      '/api/companies?unsupported_flooding_param=' + ('B' * 5000),
      '/api/companies?city=' + '<script>alert("XSS")</script>'.repeat(5)
    ];
    for (const url of floodingUrls) {
      const resp = await request.get(url);
      expect(resp.status()).toBe(400);
    }
  });

  test('07 rate limit headers on 400 error', async ({ request }) => {
    const resp = await request.get('/api/companies?limit=invalid_int', {
      headers: { 'CF-Connecting-IP': '10.0.0.99' }
    });
    expect(resp.status()).toBe(400);
    expect(resp.headers()['x-ratelimit-remaining']).toBeDefined();
  });

  test('08 csp hardening directives', async ({ request }) => {
    const resp = await request.get('/api/companies');
    const csp = resp.headers()['content-security-policy'] || '';
    expect(csp).not.toContain("'unsafe-inline'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'self'");
  });
});
