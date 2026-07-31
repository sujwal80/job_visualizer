import * as config from '../config.js';

export const REQUIRED_FIELDS = new Set([
  'id', 'name', 'lat', 'lng', 'city', 'experience', 
  'salary', 'job_type', 'skills', 'logo_url', 'url', 'description',
  'head_count', 'funding_stage', 'verified_email', 'founder_names',
  'job_openings', 'job_titles', 'jobs', 'job_count',
  'title', 'department', 'source', 'posted_date', 'job_url'
]);

export function sanitizeString(val) {
  if (val === null || val === undefined) return "";
  if (typeof val !== 'string') return val;
  
  let prev = "";
  let clean = val;
  while (prev !== clean) {
    prev = clean;
    clean = clean.replace(/<[^<>]*>/g, '');
  }
  return clean.replace(/</g, '').replace(/>/g, '').replace(/\x00/g, '').trim();
}

export function safeFloat(val, defaultVal = null) {
  if (val === null || val === undefined) return defaultVal;
  const f = parseFloat(val);
  if (isNaN(f) || !isFinite(f)) return defaultVal;
  return f;
}

export function checkHasPin(s) {
  if (s.is_remote_office === true) return false;
  const lat = safeFloat(s.lat);
  const lng = safeFloat(s.lng);
  if (lat === null || lng === null) return false;
  
  for (const [fLat, fLng] of config.FALLBACK_COORDINATES) {
    if (Math.abs(lat - fLat) < config.PIN_DELTA_THRESHOLD && Math.abs(lng - fLng) < config.PIN_DELTA_THRESHOLD) {
      return false;
    }
  }
  const addr = (s.address || s.street_address || s.bangalore_address || s.city || "").trim().toLowerCase();
  if (config.GENERIC_HUB_LABELS.has(addr)) return false;
  return true;
}

export function sanitizeUrl(url) {
  if (!url || typeof url !== 'string') return "";
  const urlClean = url.trim();
  const lower = urlClean.replace(/[\x00-\x20\x7f\u200b-\u200f\u2028\u2029\ufeff]/g, '').toLowerCase();
  const dangerousSchemes = ["javascript:", "data:", "vbscript:", "file:", "about:", "blob:", "view-source:", "mhtml:"];
  if (dangerousSchemes.some(scheme => lower.startsWith(scheme))) return "";
  
  const decodedLower = lower.replace(/&#58;/g, ":").replace(/%3a/g, ":").replace(/&#x3a;/g, ":").replace(/&colon;/g, ":");
  if (dangerousSchemes.some(scheme => decodedLower.startsWith(scheme))) return "";
  return urlClean;
}

export function validateQueryParams(urlSearchParams) {
  const allowedParams = new Set([
    'min_lat', 'max_lat', 'min_lng', 'max_lng', 'limit', 'city', 'skill',
    'industry', 'search', 'dept', 'experience', 'exp', 'has_jobs',
    'role', 'salary_min', 'exp_level', 'work_type'
  ]);
  
  let totalParams = 0;
  for (const [key, value] of urlSearchParams.entries()) {
    totalParams++;
    if (!allowedParams.has(key)) {
      return [false, `Unsupported query parameter: '${key}'`];
    }
    if (urlSearchParams.getAll(key).length > 5) {
      return [false, `Parameter flooding detected: too many duplicate values for parameter '${key}'`];
    }
    if (value.length > 100) {
      return [false, `Parameter '${key}' exceeds maximum length of 100`];
    }
    const lower = value.toLowerCase();
    const hasInjection = ["<", ">", "'", '"', ";", "--", "/*", "*/", "\x00"].some(char => value.includes(char)) ||
                         ["javascript:", "data:", "vbscript:", "union select", "drop table", "insert into", "delete from", "update ", "exec(", "execute(", "or 1=1", "or true"].some(kw => lower.includes(kw));
    if (hasInjection) {
      return [false, `Parameter '${key}' contains invalid characters or injection attempts`];
    }
  }
  
  if (totalParams > 20) {
    return [false, "Parameter flooding detected: total parameter values exceed maximum limit of 20"];
  }
  
  const floatBounds = {
    'min_lat': [-90.0, 90.0], 'max_lat': [-90.0, 90.0],
    'min_lng': [-180.0, 180.0], 'max_lng': [-180.0, 180.0]
  };
  for (const [param, [low, high]] of Object.entries(floatBounds)) {
    if (urlSearchParams.has(param)) {
      for (const item of urlSearchParams.getAll(param)) {
        if (item !== '') {
          const val = parseFloat(item);
          if (isNaN(val) || !isFinite(val) || val < low || val > high) {
            return [false, `Parameter '${param}' out of bounds [${low}, ${high}]`];
          }
        }
      }
    }
  }
  
  if (urlSearchParams.has('limit')) {
    for (const item of urlSearchParams.getAll('limit')) {
      if (item !== '') {
        const val = parseInt(item, 10);
        if (isNaN(val) || val < 0 || val > 5000) {
          return [false, "Parameter 'limit' must be an integer between 0 and 5000"];
        }
      }
    }
  }
  
  if (urlSearchParams.has('salary_min')) {
    for (const item of urlSearchParams.getAll('salary_min')) {
      if (item !== '') {
        const val = parseFloat(item);
        if (isNaN(val) || val < 0) {
          return [false, "Parameter 'salary_min' must be a non-negative number"];
        }
      }
    }
  }
  
  return [true, null];
}

export function stripRedundant(obj) {
  if (typeof obj === 'number') {
    if (isNaN(obj) || !isFinite(obj)) return 0.0;
    return obj;
  }
  if (Array.isArray(obj)) {
    return obj
      .map(stripRedundant)
      .filter(x => x !== null && !(typeof x === 'number' && (isNaN(x) || !isFinite(x))));
  }
  if (obj !== null && typeof obj === 'object') {
    const cleaned = {};
    for (const [k, v] of Object.entries(obj)) {
      let val = v;
      if (typeof v === 'number' && (isNaN(v) || !isFinite(v))) {
        val = (k === 'lat' || k === 'lng') ? 0.0 : null;
      }
      if (REQUIRED_FIELDS.has(k)) {
        cleaned[k] = (val !== null && typeof val === 'object') ? stripRedundant(val) : (val !== null && val !== undefined ? val : "");
      } else {
        if (val === null || val === undefined) {
          cleaned[k] = "";
        } else if (Array.isArray(val) && val.length === 0) {
          continue;
        } else if (typeof val === 'object' && Object.keys(val).length === 0) {
          continue;
        } else {
          if (typeof val === 'object') {
            const nested = stripRedundant(val);
            if (nested !== null && !isEmpty(nested)) cleaned[k] = nested;
          } else {
            cleaned[k] = val;
          }
        }
      }
    }
    return cleaned;
  }
  return obj;
}

function isEmpty(val) {
  if (Array.isArray(val)) return val.length === 0;
  if (val !== null && typeof val === 'object') return Object.keys(val).length === 0;
  return false;
}
