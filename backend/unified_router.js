import * as config from './config.js';
import { validateQueryParams, safeFloat, stripRedundant } from './utils/validators.js';
import { checkRateLimit } from './utils/rate_limiter.js';
import {
  generateOauthState, validateOauthState, getGoogleAuthUrl,
  exchangeCodeForUser, issueJwtToken, verifyJwtToken, revokeJwtToken
} from './services/auth_service.js';
import {
  loadStartupsUnified, filterAndSortStartups, formatStartupSummary, formatStartupDetails, formatLightweightSummary, getDataVersion
} from './services/startup_service.js';

export function getRequestOrigin(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol && parsed.host) {
      return `${parsed.protocol}//${parsed.host}`;
    }
  } catch (e) {}
  return "http://127.0.0.1:5001";
}

export function isSafeRedirect(url) {
  if (!url) return false;
  return url.startsWith('/') && !url.startsWith('//') && !url.startsWith('/\\');
}

export class CaseInsensitiveMap {
  constructor(headers) {
    this.store = new Map();
    if (headers) {
      if (headers instanceof Map) {
        for (const [k, v] of headers.entries()) this.store.set(k.toLowerCase(), v);
      } else if (typeof headers.entries === 'function') {
        for (const [k, v] of headers.entries()) this.store.set(k.toLowerCase(), v);
      } else if (typeof headers === 'object') {
        for (const [k, v] of Object.entries(headers)) this.store.set(k.toLowerCase(), v);
      }
    }
  }
  get(key, defaultVal = null) {
    return this.store.has(key.toLowerCase()) ? this.store.get(key.toLowerCase()) : defaultVal;
  }
  has(key) {
    return this.store.has(key.toLowerCase());
  }
}

export class QueryParamsWrapper {
  constructor(urlSearchParams) {
    this.params = urlSearchParams || new URLSearchParams();
  }
  getlist(key) {
    return this.params.getAll(key);
  }
  get(key, options = {}) {
    const { default: defaultVal = null, type = null } = options;
    const val = this.params.get(key);
    if (val === null) return defaultVal;
    if (type === Number) {
      const parsed = parseFloat(val);
      return isNaN(parsed) ? defaultVal : parsed;
    }
    if (type === 'int') {
      const parsed = parseInt(val, 10);
      return isNaN(parsed) ? defaultVal : parsed;
    }
    return val;
  }
  has(key) {
    return this.params.has(key);
  }
}

export class UnifiedRequest {
  constructor(options) {
    const { method, path, url, headers, queryParams, body, cookies, testing = false, env = {}, clientIp } = options;
    this.method = method.toUpperCase();
    this.path = path;
    this.url = url;
    this.headers = new CaseInsensitiveMap(headers);
    this.queryParams = new QueryParamsWrapper(queryParams);
    this.body = body;
    this.testing = testing;
    this.env = env;
    
    this.cookies = cookies || {};
    if (Object.keys(this.cookies).length === 0 && this.headers.has("cookie")) {
      const cookieStr = this.headers.get("cookie") || "";
      this.cookies = parseCookies(cookieStr);
    }
    
    this.clientIp = clientIp || 
                    this.headers.get("cf-connecting-ip") || 
                    this.headers.get("x-forwarded-for")?.split(',')[0].trim() || 
                    "127.0.0.1";
  }
  getCookie(name) {
    return this.cookies[name];
  }
}

function parseCookies(cookieStr) {
  const list = {};
  if (!cookieStr) return list;
  cookieStr.split(';').forEach(cookie => {
    const parts = cookie.split('=');
    const name = parts.shift().trim();
    const val = parts.join('=').trim();
    if (name) list[name] = decodeURIComponent(val);
  });
  return list;
}

export class UnifiedResponse {
  constructor(body, status = 200, headers = {}) {
    this.body = body;
    this.status = status;
    this.headers = headers;
    this.cookies = [];
  }
  setCookie(name, value, options = {}) {
    this.cookies.push({
      name, value,
      max_age: options.maxAge,
      httponly: options.httpOnly,
      secure: options.secure,
      samesite: options.sameSite,
      expires: options.expires,
      path: options.path || '/'
    });
  }
}

export class UnifiedRouter {
  async handleRequest(req) {
    const clientIp = req.clientIp;
    
    let token = req.getCookie('session_token') || req.getCookie('auth_token') || req.getCookie('jwt_token');
    if (!token) {
      const authHeader = req.headers.get('Authorization') || "";
      if (authHeader.startsWith('Bearer ')) {
        token = authHeader.substring(7);
      }
    }
    
    let user = null;
    if (token) {
      const sessionStore = req.env?.SESSION_STORE || config.SESSION_STORE;
      user = await verifyJwtToken(token, null, sessionStore);
    }
    
    const db = req.env?.DB || config.DB;
    
    let rateKey, limitVal;
    if (user) {
      const userId = user.sub || String(user.id || "");
      rateKey = `auth:${userId}`;
      limitVal = config.RATE_LIMIT_AUTH;
    } else {
      rateKey = `anon:${clientIp}`;
      limitVal = config.RATE_LIMIT_ANON;
    }
    
    let allowed, retryAfter, remaining;
    if (req.testing && ["127.0.0.1", "::1", "localhost"].includes(clientIp)) {
      [allowed, retryAfter, remaining, limitVal] = [true, 0, 9999, limitVal];
    } else {
      [allowed, retryAfter, remaining, limitVal] = checkRateLimit(rateKey, limitVal);
    }
    
    const rateLimitInfo = { limit: limitVal, remaining };
    if (!allowed) {
      const res = new UnifiedResponse({ error: "Rate limit exceeded. Please try again later." }, 429);
      res.headers['Retry-After'] = String(retryAfter);
      return await this.injectHeadersAsync(res, req, rateLimitInfo);
    }
    
    try {
      const cleanPath = "/" + req.path.replace(/^\/+|\/+$/g, '');
      const parts = cleanPath.split("/").filter(Boolean);
      
      let isProtected = false;
      if (parts.length >= 2) {
        if (parts[0] === 'api' && (['user', 'protected'].includes(parts[1]) || parts[parts.length - 1] === 'export')) {
          isProtected = true;
        }
      }
      
      if (isProtected) {
        if (!token) {
          const res = new UnifiedResponse({ error: "Unauthenticated. Missing JWT session token." }, 401);
          return await this.injectHeadersAsync(res, req, rateLimitInfo);
        }
        if (!user) {
          const res = new UnifiedResponse({ error: "Unauthenticated. Invalid, expired, or revoked JWT session token." }, 401);
          return await this.injectHeadersAsync(res, req, rateLimitInfo);
        }
      }
      
      if ((parts.length === 2 && parts[0] === 'api' && ['companies', 'company'].includes(parts[1])) && req.method === 'GET') {
        const [isValid, errMsg] = validateQueryParams(req.queryParams.params);
        if (!isValid) {
          return await this.injectHeadersAsync(new UnifiedResponse({ error: errMsg }, 400), req, rateLimitInfo);
        }
        
        const startups = await loadStartupsUnified(req.env);
        const minLat = safeFloat(req.queryParams.get('min_lat'));
        const maxLat = safeFloat(req.queryParams.get('max_lat'));
        const minLng = safeFloat(req.queryParams.get('min_lng'));
        const maxLng = safeFloat(req.queryParams.get('max_lng'));
        const limit = req.queryParams.get('limit', { default: 500, type: 'int' });
        
        const filtered = filterAndSortStartups(startups, minLat, maxLat, minLng, maxLng, limit, {
          cityQuery: (req.queryParams.get('city') || '').toLowerCase(),
          skillQuery: (req.queryParams.get('skill') || '').toLowerCase(),
          industryQuery: (req.queryParams.get('industry') || '').toLowerCase(),
          searchQuery: (req.queryParams.get('search') || '').toLowerCase(),
          deptQuery: (req.queryParams.get('dept') || '').toLowerCase(),
          expQuery: (req.queryParams.get('experience') || req.queryParams.get('exp') || '').toLowerCase(),
          hasJobs: ['true', '1', 'yes'].includes(String(req.queryParams.get('has_jobs')).toLowerCase()),
          roleQuery: (req.queryParams.get('role') || '').toLowerCase(),
          salaryMinQuery: safeFloat(req.queryParams.get('salary_min')),
          expLevelQuery: (req.queryParams.get('exp_level') || '').toLowerCase(),
          workTypeQuery: (req.queryParams.get('work_type') || '').toLowerCase()
        });
        
        const hasJobs = ['true', '1', 'yes'].includes(String(req.queryParams.get('has_jobs')).toLowerCase());
        const lightList = filtered.map(s => hasJobs ? formatLightweightSummary(s) : formatStartupSummary(s));
        const leanPayload = stripRedundant(lightList);
        
        const res = new UnifiedResponse(leanPayload, 200, { 'Cache-Control': 'public, max-age=60' });
        return await this.injectHeadersAsync(res, req, rateLimitInfo);
      }
      
      if (parts.length === 3 && parts[0] === 'api' && ['companies', 'company'].includes(parts[1]) && parts[2] !== 'export' && req.method === 'GET') {
        const startupId = parts[2];
        const [isValid, errMsg] = validateQueryParams(req.queryParams.params);
        if (!isValid) {
          return await this.injectHeadersAsync(new UnifiedResponse({ error: errMsg }, 400), req, rateLimitInfo);
        }
        
        const startups = await loadStartupsUnified(req.env);
        const roleQuery = (req.queryParams.get('role') || '').toLowerCase();
        const salaryMinQuery = safeFloat(req.queryParams.get('salary_min'));
        const expLevelQuery = (req.queryParams.get('exp_level') || '').toLowerCase();
        const workTypeQuery = (req.queryParams.get('work_type') || '').toLowerCase();
        const hasJobFilters = !!(roleQuery || salaryMinQuery !== null || expLevelQuery || workTypeQuery);
        
        const idsMatch = (id1, id2) => String(id1).trim().split('.')[0] === String(id2).trim().split('.')[0];
        
        for (const s of startups) {
          if (idsMatch(s.id, startupId)) {
            let targetStartup = s;
            if (hasJobFilters) {
              const filteredJobs = (s.job_openings || []).filter(j => {
                if (typeof j !== 'object') return false;
                if (roleQuery && !j.title.toLowerCase().includes(roleQuery)) return false;
                if (salaryMinQuery !== null) {
                  const maxSal = parseMaxSalary(j.salary);
                  if (maxSal === null || maxSal < salaryMinQuery) return false;
                }
                if (expLevelQuery && !matchExpLevel(j.experience || "", expLevelQuery)) return false;
                if (workTypeQuery && !matchWorkType(j, workTypeQuery, s.is_remote_office)) return false;
                return true;
              });
              targetStartup = { ...s, job_openings: filteredJobs };
            }
            
            const leanPayload = formatStartupDetails(targetStartup);
            const res = new UnifiedResponse(leanPayload, 200, { 'Cache-Control': 'public, max-age=60' });
            return await this.injectHeadersAsync(res, req, rateLimitInfo);
          }
        }
        return await this.injectHeadersAsync(new UnifiedResponse({ error: "Startup not found" }, 404), req, rateLimitInfo);
      }
      
      if (parts.length === 3 && parts[0] === 'api' && parts[1] === 'auth' && parts[2] === 'google' && req.method === 'GET') {
        const sessionStore = req.env?.SESSION_STORE || config.SESSION_STORE;
        const stateToken = await generateOauthState(600, sessionStore);
        let nextPath = req.queryParams.get('next') || '/';
        if (!isSafeRedirect(nextPath)) nextPath = '/';
        
        const combinedState = `${stateToken}:${nextPath}`;
        const requestOrigin = getRequestOrigin(req.url);
        const redirectUri = req.queryParams.get('redirect_uri') || `${requestOrigin}/api/auth/callback`;
        const authUrl = getGoogleAuthUrl(combinedState, redirectUri);
        
        const headers = { 'Location': authUrl };
        let res;
        if (['true', '1', 'yes'].includes(String(req.queryParams.get('redirect')).toLowerCase())) {
          res = new UnifiedResponse("", 302, headers);
        } else {
          res = new UnifiedResponse({ auth_url: authUrl, state: combinedState }, 200, headers);
        }
        
        const isProd = config.ENVIRONMENT === 'production';
        res.setCookie('oauth_state', stateToken, { maxAge: 600, httpOnly: true, secure: isProd, sameSite: 'Lax' });
        return await this.injectHeadersAsync(res, req, rateLimitInfo);
      }
      
      const isCallback = (parts.length === 3 && parts[0] === 'api' && parts[1] === 'auth' && parts[2] === 'callback') ||
                         (parts.length === 4 && parts[0] === 'api' && parts[1] === 'auth' && parts[2] === 'google' && parts[3] === 'callback');
      if (isCallback && ['GET', 'POST'].includes(req.method)) {
        let bodyData = {};
        if (req.method === 'POST') {
          if (typeof req.body === 'object') bodyData = req.body || {};
          else if (typeof req.body === 'string' && req.body) {
            try { bodyData = JSON.parse(req.body); } catch (e) {}
          }
        }
        
        const combinedState = req.queryParams.get('state') || bodyData.state || "";
        const code = req.queryParams.get('code') || bodyData.code;
        
        let stateToken, nextPath;
        if (combinedState.includes(':')) {
          [stateToken, nextPath] = combinedState.split(':');
        } else {
          stateToken = combinedState;
          nextPath = '/';
        }
        if (!isSafeRedirect(nextPath)) nextPath = '/';
        
        const sessionStore = req.env?.SESSION_STORE || config.SESSION_STORE;
        const cookieState = req.getCookie('oauth_state');
        
        if (!cookieState || cookieState !== stateToken) {
          return await this.injectHeadersAsync(new UnifiedResponse({ error: "CSRF state validation failed. Cookie state mismatch or missing." }, 400), req, rateLimitInfo);
        }
        
        const validInStore = await validateOauthState(stateToken, sessionStore);
        if (!validInStore) {
          return await this.injectHeadersAsync(new UnifiedResponse({ error: "CSRF state validation failed. State token expired or already used." }, 400), req, rateLimitInfo);
        }
        
        if (!code) {
          return await this.injectHeadersAsync(new UnifiedResponse({ error: "Missing authorization code." }, 400), req, rateLimitInfo);
        }
        
        const requestOrigin = getRequestOrigin(req.url);
        const redirectUri = req.queryParams.get('redirect_uri') || `${requestOrigin}/api/auth/callback`;
        try {
          const userData = await exchangeCodeForUser(code, redirectUri);
          const token = await issueJwtToken(userData);
          
          const res = new UnifiedResponse("", 302, { 'Location': nextPath });
          const isProd = config.ENVIRONMENT === 'production';
          res.setCookie('session_token', token, { maxAge: 3600, httpOnly: true, secure: isProd, sameSite: 'Strict' });
          res.setCookie('oauth_state', '', { expires: 'Thu, 01 Jan 1970 00:00:00 GMT', httpOnly: true, secure: isProd, sameSite: 'Lax' });
          return await this.injectHeadersAsync(res, req, rateLimitInfo);
        } catch (e) {
          return await this.injectHeadersAsync(new UnifiedResponse({ error: e.message }, 400), req, rateLimitInfo);
        }
      }
      
      if (parts.length === 3 && parts[0] === 'api' && parts[1] === 'auth' && parts[2] === 'demo_login' && ['GET', 'POST'].includes(req.method)) {
        if (config.ENVIRONMENT === 'production') {
          return await this.injectHeadersAsync(new UnifiedResponse({ error: "Demo login backdoor is disabled in production." }, 403), req, rateLimitInfo);
        }
        
        const demoUser = {
          sub: "usr_google_1001",
          email: "ujwal@worldtech.map",
          name: "Ujwal Singh",
          picture: "https://lh3.googleusercontent.com/a/mockphoto1"
        };
        const token = await issueJwtToken(demoUser);
        
        const headers = {};
        let res;
        if (['true', '1', 'yes'].includes(String(req.queryParams.get('redirect')).toLowerCase()) || req.method === 'GET') {
          headers['Location'] = '/';
          res = new UnifiedResponse("", 302, headers);
        } else {
          res = new UnifiedResponse({
            message: "Demo sandbox authentication successful.",
            authenticated: true,
            user: demoUser,
            token: token
          }, 200, headers);
        }
        res.setCookie('session_token', token, { maxAge: 3600, httpOnly: true, secure: false, sameSite: 'Lax' });
        return await this.injectHeadersAsync(res, req, rateLimitInfo);
      }
      
      if (parts.length === 3 && parts[0] === 'api' && parts[1] === 'auth' && parts[2] === 'status' && req.method === 'GET') {
        if (!token) {
          return await this.injectHeadersAsync(new UnifiedResponse({ authenticated: false, user: null, message: "No session cookie present." }, 200), req, rateLimitInfo);
        }
        if (!user) {
          return await this.injectHeadersAsync(new UnifiedResponse({ authenticated: false, user: null, message: "Invalid, expired, or revoked session cookie." }, 200), req, rateLimitInfo);
        }
        const payload = {
          authenticated: true,
          user: {
            id: user.sub || String(user.id || ""),
            email: user.email || "",
            name: user.name || "",
            picture: user.picture || ""
          },
          expires_at: user.exp
        };
        return await this.injectHeadersAsync(new UnifiedResponse(payload, 200), req, rateLimitInfo);
      }
      
      if (parts.length === 3 && parts[0] === 'api' && parts[1] === 'auth' && parts[2] === 'logout' && ['GET', 'POST'].includes(req.method)) {
        if (token) {
          const sessionStore = req.env?.SESSION_STORE || config.SESSION_STORE;
          await revokeJwtToken(token, null, sessionStore);
        }
        const res = new UnifiedResponse({ message: "Successfully logged out.", authenticated: false }, 200);
        const isProd = config.ENVIRONMENT === 'production';
        res.setCookie('session_token', '', { expires: 'Thu, 01 Jan 1970 00:00:00 GMT', httpOnly: true, secure: isProd, sameSite: 'Strict' });
        res.setCookie('auth_token', '', { expires: 'Thu, 01 Jan 1970 00:00:00 GMT', httpOnly: true, secure: isProd, sameSite: 'Strict' });
        res.setCookie('jwt_token', '', { expires: 'Thu, 01 Jan 1970 00:00:00 GMT', httpOnly: true, secure: isProd, sameSite: 'Strict' });
        return await this.injectHeadersAsync(res, req, rateLimitInfo);
      }
      
      const isProfile = (parts.length === 3 && parts[0] === 'api' && ['user', 'protected'].includes(parts[1]) && parts[2] === 'profile');
      if (isProfile && ['GET', 'POST'].includes(req.method)) {
        const userId = user.sub || String(user.id || "");
        if (!db) {
          return await this.injectHeadersAsync(new UnifiedResponse({ error: "D1 Database not configured" }, 500), req, rateLimitInfo);
        }
        
        if (req.method === 'GET') {
          const stmt = db.prepare("SELECT id, email, name, picture, bio, skills, preferred_location, job_preferences FROM user_profiles WHERE id = ?").bind(userId);
          const row = await stmt.first();
          
          let profile;
          if (row) {
            let skills = [], jobPreferences = {};
            try { skills = JSON.parse(row.skills || "[]"); } catch (e) {}
            try { jobPreferences = JSON.parse(row.job_preferences || "{}"); } catch (e) {}
            
            profile = {
              id: row.id,
              email: row.email || "",
              name: row.name || "",
              picture: row.picture || "",
              bio: row.bio || "",
              skills,
              preferred_location: row.preferred_location || "",
              job_preferences: jobPreferences
            };
          } else {
            profile = {
              id: userId,
              email: user.email || "",
              name: user.name || "",
              picture: user.picture || "",
              bio: "",
              skills: [],
              preferred_location: "",
              job_preferences: {}
            };
            await db.prepare("INSERT INTO user_profiles (id, email, name, picture, bio, skills, preferred_location, job_preferences) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
              .bind(userId, user.email || "", user.name || "", user.picture || "", "", "[]", "", "{}")
              .run();
          }
          return await this.injectHeadersAsync(new UnifiedResponse(profile, 200), req, rateLimitInfo);
        }
        
        if (req.method === 'POST') {
          let bodyData = {};
          if (typeof req.body === 'object') bodyData = req.body || {};
          else if (typeof req.body === 'string' && req.body) {
            try { bodyData = JSON.parse(req.body); } catch (e) {}
          }
          
          const row = await db.prepare("SELECT id, email, name, picture, bio, skills, preferred_location, job_preferences FROM user_profiles WHERE id = ?").bind(userId).first();
          let existingProfile = {};
          if (row) {
            let skills = [], jobPreferences = {};
            try { skills = JSON.parse(row.skills || "[]"); } catch (e) {}
            try { jobPreferences = JSON.parse(row.job_preferences || "{}"); } catch (e) {}
            existingProfile = { ...row, skills, job_preferences: jobPreferences };
          }
          
          const email = existingProfile.email || user.email || "";
          const picture = existingProfile.picture || user.picture || "";
          const name = "name" in bodyData ? bodyData.name : (existingProfile.name || user.name || "");
          const bio = "bio" in bodyData ? bodyData.bio : (existingProfile.bio || "");
          const skills = "skills" in bodyData ? bodyData.skills : (existingProfile.skills || []);
          const preferredLocation = "preferred_location" in bodyData ? bodyData.preferred_location : (existingProfile.preferred_location || "");
          const jobPreferences = "job_preferences" in bodyData ? bodyData.job_preferences : (existingProfile.job_preferences || {});
          
          const skillsStr = JSON.stringify(skills);
          const jobPrefsStr = JSON.stringify(jobPreferences);
          
          if (row) {
            await db.prepare("UPDATE user_profiles SET email = ?, name = ?, picture = ?, bio = ?, skills = ?, preferred_location = ?, job_preferences = ? WHERE id = ?")
              .bind(email, name, picture, bio, skillsStr, preferredLocation, jobPrefsStr, userId)
              .run();
          } else {
            await db.prepare("INSERT INTO user_profiles (id, email, name, picture, bio, skills, preferred_location, job_preferences) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
              .bind(userId, email, name, picture, bio, skillsStr, preferredLocation, jobPrefsStr)
              .run();
          }
          
          const updatedProfile = { id: userId, email, name, picture, bio, skills, preferred_location: preferredLocation, job_preferences: jobPreferences };
          return await this.injectHeadersAsync(new UnifiedResponse(updatedProfile, 200), req, rateLimitInfo);
        }
      }
      
      const isBookmarks = (parts.length === 3 && parts[0] === 'api' && ['user', 'protected'].includes(parts[1]) && parts[2] === 'bookmarks');
      if (isBookmarks && ['GET', 'POST', 'DELETE'].includes(req.method)) {
        const userId = user.sub || String(user.id || "");
        if (!db) {
          return await this.injectHeadersAsync(new UnifiedResponse({ error: "D1 Database not configured" }, 500), req, rateLimitInfo);
        }
        
        if (req.method === 'GET') {
          const { results: rows } = await db.prepare("SELECT id, company_id, created_at FROM bookmarks WHERE user_id = ?").bind(userId).all();
          const startups = await loadStartupsUnified(req.env);
          
          const startupNames = {};
          for (const s of startups) {
            if (s.id && s.name) startupNames[String(s.id).trim()] = s.name;
          }
          
          const bookmarksList = [];
          for (const row of (rows || [])) {
            const companyId = row.company_id;
            const savedAt = row.created_at;
            let companyName = startupNames[String(companyId).trim()] || "Unknown";
            
            bookmarksList.push({
              id: row.id,
              company_id: companyId,
              name: companyName,
              saved_at: savedAt
            });
          }
          return await this.injectHeadersAsync(new UnifiedResponse(bookmarksList, 200), req, rateLimitInfo);
        }
        
        if (req.method === 'POST') {
          let bodyData = {};
          if (typeof req.body === 'object') bodyData = req.body || {};
          else if (typeof req.body === 'string' && req.body) {
            try { bodyData = JSON.parse(req.body); } catch (e) {}
          }
          const companyId = bodyData.company_id;
          if (!companyId) {
            return await this.injectHeadersAsync(new UnifiedResponse({ error: "Missing company_id" }, 400), req, rateLimitInfo);
          }
          
          const runRes = await db.prepare("INSERT INTO bookmarks (user_id, company_id) VALUES (?, ?)").bind(userId, String(companyId)).run();
          const bookmarkId = runRes.meta?.last_row_id;
          
          const res = new UnifiedResponse({
            success: true,
            bookmark: { id: bookmarkId, company_id: companyId, user_id: userId }
          }, 201);
          return await this.injectHeadersAsync(res, req, rateLimitInfo);
        }
        
        if (req.method === 'DELETE') {
          let companyId = req.queryParams.get("company_id");
          let bookmarkId = req.queryParams.get("bookmark_id") || req.queryParams.get("id");
          
          if (!companyId && !bookmarkId) {
            let bodyData = {};
            if (typeof req.body === 'object') bodyData = req.body || {};
            else if (typeof req.body === 'string' && req.body) {
              try { bodyData = JSON.parse(req.body); } catch (e) {}
            }
            companyId = bodyData.company_id;
            bookmarkId = bodyData.bookmark_id || bodyData.id;
          }
          
          if (!companyId && !bookmarkId) {
            return await this.injectHeadersAsync(new UnifiedResponse({ error: "Missing company_id or bookmark_id" }, 400), req, rateLimitInfo);
          }
          
          if (bookmarkId) {
            await db.prepare("DELETE FROM bookmarks WHERE id = ? AND user_id = ?").bind(bookmarkId, userId).run();
          } else {
            await db.prepare("DELETE FROM bookmarks WHERE company_id = ? AND user_id = ?").bind(String(companyId), userId).run();
          }
          return await this.injectHeadersAsync(new UnifiedResponse({ success: true, message: "Bookmark removed" }, 200), req, rateLimitInfo);
        }
      }
      
      const isExport = (parts.length === 3 && parts[0] === 'api' && ['company', 'companies', 'protected'].includes(parts[1]) && parts[2] === 'export');
      if (isExport && req.method === 'GET') {
        const startups = await loadStartupsUnified(req.env);
        const lightList = startups.slice(0, 10).map(formatStartupSummary);
        const payload = {
          authenticated: true,
          export_count: lightList.length,
          data: lightList
        };
        return await this.injectHeadersAsync(new UnifiedResponse(payload, 200), req, rateLimitInfo);
      }
      
      return await this.injectHeadersAsync(new UnifiedResponse({ error: "Not Found" }, 404), req, rateLimitInfo);
      
    } catch (e) {
      return await this.injectHeadersAsync(new UnifiedResponse({ error: "Internal server error", details: e.message }, 500), req, rateLimitInfo);
    }
  }
  
  async injectHeadersAsync(response, req, rateLimitInfo = null) {
    const headers = UnifiedRouter.injectSecurityHeaders(response.headers, req.path);
    if (rateLimitInfo) {
      headers['x-ratelimit-limit'] = String(rateLimitInfo.limit || 120);
      headers['x-ratelimit-remaining'] = String(rateLimitInfo.remaining || 120);
    }
    
    const path = req.path;
    if (path.startsWith('/api/company') || path.startsWith('/api/companies')) {
      headers['x-data-version'] = await getDataVersion();
      const exposeHeaders = headers['access-control-expose-headers'] || '';
      if (exposeHeaders) {
        if (!exposeHeaders.includes('X-Data-Version')) {
          headers['access-control-expose-headers'] = `${exposeHeaders}, X-Data-Version`;
        }
      } else {
        headers['access-control-expose-headers'] = 'X-Data-Version, X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After';
      }
    }
    
    if (response.status >= 400) {
      headers['cache-control'] = 'no-store';
    }
    response.headers = headers;
    return response;
  }
  
  static injectSecurityHeaders(headers, path) {
    const headersLower = {};
    for (const [k, v] of Object.entries(headers)) headersLower[k.toLowerCase()] = v;
    
    let csp;
    if (path.startsWith('/api/')) {
      csp = (
        "default-src 'self' https://*.tile.openstreetmap.org https://cdnjs.cloudflare.com https://cdn.tailwindcss.com; " +
        "script-src 'self' https://unpkg.com https://cdnjs.cloudflare.com https://cdn.tailwindcss.com; " +
        "style-src 'self' https://fonts.googleapis.com https://unpkg.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://cdn.tailwindcss.com; " +
        "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com https://unpkg.com https://*.cartocdn.com; " +
        "img-src 'self' data: blob: https: http:; " +
        "connect-src 'self' https://*.cartocdn.com https://*.basemaps.cartocdn.com https://basemaps.cartocdn.com https://*.maplibre.org https://*.arcgisonline.com https://*.openstreetmap.org https://*.tile.openstreetmap.org blob: data:; " +
        "worker-src 'self' blob:; " +
        "child-src 'self' blob:; " +
        "object-src 'none'; " +
        "base-uri 'self'; " +
        "frame-ancestors 'self';"
      );
    } else {
      csp = (
        "default-src 'self' https://*.tile.openstreetmap.org https://cdnjs.cloudflare.com https://cdn.tailwindcss.com; " +
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com https://cdnjs.cloudflare.com https://cdn.tailwindcss.com; " +
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://cdn.tailwindcss.com; " +
        "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com https://unpkg.com https://*.cartocdn.com; " +
        "img-src 'self' data: blob: https: http:; " +
        "connect-src 'self' https://*.cartocdn.com https://*.basemaps.cartocdn.com https://basemaps.cartocdn.com https://*.maplibre.org https://*.arcgisonline.com https://*.openstreetmap.org https://*.tile.openstreetmap.org blob: data:; " +
        "worker-src 'self' blob:; " +
        "child-src 'self' blob:; " +
        "object-src 'none'; " +
        "base-uri 'self'; " +
        "frame-ancestors 'self';"
      );
    }
    
    headersLower['content-security-policy'] = csp;
    headersLower['x-content-type-options'] = 'nosniff';
    headersLower['x-frame-options'] = 'SAMEORIGIN';
    headersLower['referrer-policy'] = 'strict-origin-when-cross-origin';
    headersLower['access-control-allow-origin'] = '*';
    headersLower['access-control-allow-methods'] = 'GET, POST, DELETE, OPTIONS';
    headersLower['access-control-allow-headers'] = 'Content-Type, Authorization, Accept, Accept-Encoding';
    headersLower['strict-transport-security'] = 'max-age=31536000; includeSubDomains';
    
    const vary = headersLower['vary'] || '';
    if (!vary) {
      headersLower['vary'] = 'Accept-Encoding';
    } else if (!vary.includes('Accept-Encoding')) {
      headersLower['vary'] = `${vary}, Accept-Encoding`;
    }
    
    return headersLower;
  }
}
