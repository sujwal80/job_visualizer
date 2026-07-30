export let ENVIRONMENT = 'development';
export let DEFAULT_TARGET_CITY = 'Bengaluru';
export let DEFAULT_MAP_CENTER_LAT = 12.9716;
export let DEFAULT_MAP_CENTER_LNG = 77.5946;
export let FALLBACK_COORDINATES = [[12.9716, 77.5946], [12.9767, 77.5900], [12.9767936, 77.590082]];
export let PIN_DELTA_THRESHOLD = 0.008;
export let GENERIC_HUB_LABELS = new Set([
  "bengaluru", "bangalore", "india", "karnataka",
  "bengaluru, karnataka", "hyderabad", "mumbai", "delhi"
]);
export let REGION_SYNONYM_MAP = {
  "usa": new Set(["usa", "us", "united states", "america", "sf", "san francisco", "california", "bay area", "ca"]),
  "uk": new Set(["uk", "united kingdom", "england", "london", "gb", "great britain"]),
  "india": new Set(["india", "in", "bengaluru", "bangalore", "karnataka", "blr"])
};
export let GOOGLE_REDIRECT_URI = "http://127.0.0.1:5001/api/auth/callback";
export let RATE_LIMIT_AUTH = 200;
export let RATE_LIMIT_ANON = 60;
export let JWT_SECRET_KEY = "worldtech_map_default_jwt_secret_key_2026_super_secure";
export let GOOGLE_CLIENT_ID = "1234567890-worldtechmapmockclientid.apps.googleusercontent.com";
export let GOOGLE_CLIENT_SECRET = "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";

// emulated D1 & KV bindings for local testing in Node, will be set in setupConfig if running in Workers
export let SESSION_STORE = null;
export let DB = null;

export function setupConfig(env) {
  if (!env) return;
  
  if (env.ENVIRONMENT) ENVIRONMENT = env.ENVIRONMENT;
  if (env.DEFAULT_TARGET_CITY) DEFAULT_TARGET_CITY = env.DEFAULT_TARGET_CITY;
  if (env.DEFAULT_MAP_CENTER_LAT) DEFAULT_MAP_CENTER_LAT = parseFloat(env.DEFAULT_MAP_CENTER_LAT);
  if (env.DEFAULT_MAP_CENTER_LNG) DEFAULT_MAP_CENTER_LNG = parseFloat(env.DEFAULT_MAP_CENTER_LNG);
  
  if (env.FALLBACK_COORDINATES) {
    const coords = [];
    for (const pair of env.FALLBACK_COORDINATES.split(";")) {
      const parts = pair.split(",");
      if (parts.length === 2) {
        const lat = parseFloat(parts[0]);
        const lng = parseFloat(parts[1]);
        if (!isNaN(lat) && !isNaN(lng)) coords.push([lat, lng]);
      }
    }
    if (coords.length > 0) FALLBACK_COORDINATES = coords;
  }
  
  if (env.PIN_DELTA_THRESHOLD) PIN_DELTA_THRESHOLD = parseFloat(env.PIN_DELTA_THRESHOLD);
  
  if (env.GENERIC_HUB_LABELS) {
    GENERIC_HUB_LABELS = new Set(env.GENERIC_HUB_LABELS.split(",").map(x => x.trim().toLowerCase()));
  }
  
  if (env.REGION_SYNONYM_MAP) {
    try {
      const parsed = JSON.parse(env.REGION_SYNONYM_MAP);
      const newMap = {};
      for (const [k, v] of Object.entries(parsed)) {
        newMap[k.toLowerCase()] = new Set(v.map(x => x.toLowerCase()));
      }
      REGION_SYNONYM_MAP = newMap;
    } catch (e) {
      // ignore
    }
  }
  
  if (env.GOOGLE_REDIRECT_URI) GOOGLE_REDIRECT_URI = env.GOOGLE_REDIRECT_URI;
  if (env.RATE_LIMIT_AUTH) RATE_LIMIT_AUTH = parseInt(env.RATE_LIMIT_AUTH, 10);
  if (env.RATE_LIMIT_ANON) RATE_LIMIT_ANON = parseInt(env.RATE_LIMIT_ANON, 10);
  if (env.JWT_SECRET_KEY) JWT_SECRET_KEY = env.JWT_SECRET_KEY;
  if (env.GOOGLE_CLIENT_ID) GOOGLE_CLIENT_ID = env.GOOGLE_CLIENT_ID;
  if (env.GOOGLE_CLIENT_SECRET) GOOGLE_CLIENT_SECRET = env.GOOGLE_CLIENT_SECRET;

  if (env.SESSION_STORE) SESSION_STORE = env.SESSION_STORE;
  if (env.DB) DB = env.DB;
}
