import { UnifiedRequest, UnifiedResponse, UnifiedRouter } from '../backend/unified_router.js';
import { resetAuthStores, issueJwtToken } from '../backend/services/auth_service.js';
import { rateLimits } from '../backend/utils/rate_limiter.js';
import * as startupService from '../backend/services/startup_service.js';

jest.mock('../backend/services/startup_service.js', () => {
  const original = jest.requireActual('../backend/services/startup_service.js');
  return {
    ...original,
    loadStartupsUnified: jest.fn(),
    getDataVersion: jest.fn()
  };
});

describe('UnifiedRequest and UnifiedResponse Adapters', () => {
  test('request headers case insensitivity', () => {
    const req = new UnifiedRequest({
      method: "GET",
      path: "/api/test",
      url: "http://localhost/api/test",
      headers: { "Authorization": "Bearer token123", "x-custom-header": "value" }
    });
    expect(req.headers.get("authorization")).toBe("Bearer token123");
    expect(req.headers.get("AUTHORIZATION")).toBe("Bearer token123");
    expect(req.headers.get("x-custom-header")).toBe("value");
    expect(req.headers.get("X-CUSTOM-HEADER")).toBe("value");
    expect(req.headers.get("nonexistent")).toBeNull();
  });

  test('request cookies extraction', () => {
    // Case 1: passed directly
    const req1 = new UnifiedRequest({
      method: "GET",
      path: "/api/test",
      url: "http://localhost/api/test",
      cookies: { "session_token": "token123" }
    });
    expect(req1.getCookie("session_token")).toBe("token123");

    // Case 2: extracted from header
    const req2 = new UnifiedRequest({
      method: "GET",
      path: "/api/test",
      url: "http://localhost/api/test",
      headers: { "Cookie": "session_token=token456; other_cookie=val" }
    });
    expect(req2.getCookie("session_token")).toBe("token456");
    expect(req2.getCookie("other_cookie")).toBe("val");
  });

  test('request query parameters', () => {
    const params = new URLSearchParams();
    params.append("limit", "10");
    params.append("multi", "a");
    params.append("multi", "b");
    
    const req = new UnifiedRequest({
      method: "GET",
      path: "/api/test",
      url: "http://localhost/api/test",
      queryParams: params
    });
    expect(req.queryParams.get("limit")).toBe("10");
    expect(req.queryParams.get("limit", { type: 'int' })).toBe(10);
    expect(req.queryParams.getlist("multi")).toEqual(["a", "b"]);
    expect(req.queryParams.getlist("nonexistent")).toEqual([]);
    expect(req.queryParams.get("nonexistent", { default: "fallback" })).toBe("fallback");
  });

  test('response set cookie', () => {
    const res = new UnifiedResponse("OK", 200);
    res.setCookie("test_cookie", "val123", { maxAge: 3600, httpOnly: true });
    expect(res.cookies.length).toBe(1);
    const cookie = res.cookies[0];
    expect(cookie.name).toBe("test_cookie");
    expect(cookie.value).toBe("val123");
    expect(cookie.max_age).toBe(3600);
    expect(cookie.httponly).toBe(true);
  });
});

describe('UnifiedRouter Tests', () => {
  let router;

  beforeEach(() => {
    router = new UnifiedRouter();
    resetAuthStores();
    rateLimits.clear();
    jest.clearAllMocks();
  });

  test('rate limiting bypass on testing localhost', async () => {
    const req = new UnifiedRequest({
      method: "GET",
      path: "/api/companies",
      url: "http://localhost/api/companies",
      testing: true,
      clientIp: "127.0.0.1"
    });
    startupService.loadStartupsUnified.mockResolvedValue([]);
    const res = await router.handleRequest(req);
    expect(res.status).not.toBe(429);
  });

  test('invalid query parameters trigger 400', async () => {
    const params = new URLSearchParams();
    params.set("invalid_param", "val");
    const req = new UnifiedRequest({
      method: "GET",
      path: "/api/companies",
      url: "http://localhost/api/companies",
      queryParams: params,
      testing: true,
      clientIp: "127.0.0.1"
    });
    const res = await router.handleRequest(req);
    expect(res.status).toBe(400);
    expect(res.body.error).toContain("Unsupported query parameter");
  });

  test('companies listing success and security headers', async () => {
    startupService.getDataVersion.mockResolvedValue("1");
    startupService.loadStartupsUnified.mockResolvedValue([
      { id: 1, name: "AI Corp", lat: 12.95, lng: 77.60, city: "Bengaluru", experience: "Entry", salary: "10L", job_type: "Full-time", skills: ["Python"], logo_url: "", url: "", description: "", head_count: 10, funding_stage: "Seed", verified_email: "a@a.com", founder_names: ["A"] }
    ]);

    const req = new UnifiedRequest({
      method: "GET",
      path: "/api/companies",
      url: "http://localhost/api/companies",
      testing: true,
      clientIp: "127.0.0.1"
    });

    const res = await router.handleRequest(req);
    expect(res.status).toBe(200);
    expect(res.body.length).toBe(1);
    expect(res.body[0].name).toBe("AI Corp");
    expect(res.headers['content-security-policy']).toBeDefined();
    expect(res.headers['x-content-type-options']).toBe("nosniff");
    expect(res.headers['x-frame-options']).toBe("SAMEORIGIN");
    expect(res.headers['x-data-version']).toBe("1");
  });

  test('company details success and 404', async () => {
    startupService.loadStartupsUnified.mockResolvedValue([
      { id: "1", name: "AI Corp", lat: 12.95, lng: 77.60, city: "Bengaluru", experience: "Entry", salary: "10L", job_type: "Full-time", skills: ["Python"], logo_url: "", url: "", description: "", head_count: 10, funding_stage: "Seed", verified_email: "a@a.com", founder_names: ["A"], job_openings: [] }
    ]);

    const reqOk = new UnifiedRequest({
      method: "GET",
      path: "/api/company/1",
      url: "http://localhost/api/company/1",
      testing: true,
      clientIp: "127.0.0.1"
    });
    const resOk = await router.handleRequest(reqOk);
    expect(resOk.status).toBe(200);
    expect(resOk.body.name).toBe("AI Corp");

    const req404 = new UnifiedRequest({
      method: "GET",
      path: "/api/company/999",
      url: "http://localhost/api/company/999",
      testing: true,
      clientIp: "127.0.0.1"
    });
    const res404 = await router.handleRequest(req404);
    expect(res404.status).toBe(404);
    expect(res404.body.error).toBe("Startup not found");
  });

  test('google auth URL flow', async () => {
    const req = new UnifiedRequest({
      method: "GET",
      path: "/api/auth/google",
      url: "http://localhost/api/auth/google",
      testing: true,
      clientIp: "127.0.0.1"
    });
    const res = await router.handleRequest(req);
    expect(res.status).toBe(200);
    expect(res.body.auth_url).toBeDefined();
    expect(res.body.state).toBeDefined();
  });

  test('authenticated profile GET & POST using mock D1', async () => {
    const user = { sub: "usr_1001", email: "test@worldtech.map", name: "Test User" };
    const token = await issueJwtToken(user);

    // Mock D1 Database APIs
    const mockDb = {
      prepare: jest.fn().mockReturnThis(),
      bind: jest.fn().mockReturnThis(),
      first: jest.fn(),
      run: jest.fn().mockResolvedValue({ meta: { last_row_id: 1 } })
    };

    // Test GET profile - Non-existent profile inserts default
    mockDb.first.mockResolvedValueOnce(null); // Profile does not exist yet

    const reqGet = new UnifiedRequest({
      method: "GET",
      path: "/api/user/profile",
      url: "http://localhost/api/user/profile",
      headers: { "Authorization": `Bearer ${token}` },
      testing: true,
      clientIp: "127.0.0.1",
      env: { DB: mockDb }
    });

    const resGet = await router.handleRequest(reqGet);
    expect(resGet.status).toBe(200);
    expect(resGet.body.email).toBe("test@worldtech.map");
    expect(mockDb.prepare).toHaveBeenCalledWith(expect.stringContaining("INSERT INTO user_profiles"));

    // Test POST profile - updates details
    mockDb.first.mockResolvedValueOnce({ id: "usr_1001", email: "test@worldtech.map", name: "Test User" }); // Profile exists

    const reqPost = new UnifiedRequest({
      method: "POST",
      path: "/api/user/profile",
      url: "http://localhost/api/user/profile",
      headers: { "Authorization": `Bearer ${token}` },
      body: JSON.stringify({ name: "Updated Name", bio: "Developer Bio" }),
      testing: true,
      clientIp: "127.0.0.1",
      env: { DB: mockDb }
    });

    const resPost = await router.handleRequest(reqPost);
    expect(resPost.status).toBe(200);
    expect(resPost.body.name).toBe("Updated Name");
    expect(resPost.body.bio).toBe("Developer Bio");
  });
});
