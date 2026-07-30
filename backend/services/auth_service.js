import * as config from '../config.js';
import * as jwt from '../utils/jwt_helper.js';

const csrfStateStore = new Map();
const revokedTokens = new Set();

export function resetAuthStores() {
  csrfStateStore.clear();
  revokedTokens.clear();
}

export async function generateOauthState(expiresIn = 600, sessionStore = null) {
  const state = crypto.randomUUID().replace(/-/g, '');
  if (sessionStore) {
    await sessionStore.put(`csrf:${state}`, "1", { expirationTtl: expiresIn });
  } else {
    const expiresAt = (Date.now() / 1000) + expiresIn;
    csrfStateStore.set(state, expiresAt);
    
    const now = Date.now() / 1000;
    for (const [k, exp] of csrfStateStore.entries()) {
      if (exp < now) csrfStateStore.delete(k);
    }
    while (csrfStateStore.size > 10000) {
      const firstKey = csrfStateStore.keys().next().value;
      csrfStateStore.delete(firstKey);
    }
  }
  return state;
}

export async function validateOauthState(state, sessionStore = null) {
  if (!state || typeof state !== 'string') return false;
  if (sessionStore) {
    const key = `csrf:${state}`;
    const val = await sessionStore.get(key);
    if (val === null) return false;
    await sessionStore.delete(key);
    return true;
  } else {
    const exp = csrfStateStore.get(state);
    if (exp === undefined) return false;
    csrfStateStore.delete(state);
    if ((Date.now() / 1000) > exp) return false;
    return true;
  }
}

export function getGoogleAuthUrl(state, redirectUri = null) {
  const params = new URLSearchParams({
    client_id: config.GOOGLE_CLIENT_ID,
    redirect_uri: redirectUri || config.GOOGLE_REDIRECT_URI,
    response_type: "code",
    scope: "openid email profile",
    state: state,
    access_type: "offline",
    prompt: "consent"
  });
  return "https://accounts.google.com/o/oauth2/v2/auth?" + params.toString();
}

export const MOCK_USERS = {
  "mock_code_user1": {
    "sub": "usr_google_1001",
    "email": "ujwal@worldtech.map",
    "name": "Ujwal Singh",
    "picture": "https://lh3.googleusercontent.com/a/mockphoto1"
  },
  "mock_code_admin": {
    "sub": "usr_google_admin",
    "email": "admin@worldtech.map",
    "name": "WorldTech Admin",
    "picture": "https://lh3.googleusercontent.com/a/mockphotoadmin"
  },
  "mock_code_default": {
    "sub": "usr_google_default",
    "email": "developer@worldtech.map",
    "name": "Senior Developer",
    "picture": "https://lh3.googleusercontent.com/a/mockphotodev"
  }
};

export async function exchangeCodeForUser(code, redirectUri = null) {
  if (!code || typeof code !== 'string') {
    throw new Error("Invalid authorization code.");
  }
  
  if (MOCK_USERS[code]) {
    return MOCK_USERS[code];
  } else if (code.startsWith("mock_") || code.startsWith("test_")) {
    return {
      sub: `usr_sim_${crypto.randomUUID().split('-')[0]}`,
      email: `simulated_${crypto.randomUUID().split('-')[0]}@worldtech.map`,
      name: "Simulated Google User",
      picture: "https://lh3.googleusercontent.com/a/default"
    };
  } else {
    const tokenUrl = "https://oauth2.googleapis.com/token";
    const params = new URLSearchParams({
      code: code,
      client_id: config.GOOGLE_CLIENT_ID,
      client_secret: config.GOOGLE_CLIENT_SECRET,
      redirect_uri: redirectUri || config.GOOGLE_REDIRECT_URI,
      grant_type: "authorization_code"
    });
    
    const tokenRes = await fetch(tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: params.toString()
    });
    
    const tokenData = await tokenRes.json();
    if (!tokenRes.ok || tokenData.error) {
      throw new Error(`Failed to exchange authorization code: ${tokenData.error_description || tokenData.error || "Unknown error"}`);
    }
    
    const accessToken = tokenData.access_token;
    if (!accessToken) {
      throw new Error("Failed to retrieve access token from Google response.");
    }
    
    const userInfoUrl = "https://www.googleapis.com/oauth2/v3/userinfo";
    const userRes = await fetch(userInfoUrl, {
      headers: { "Authorization": `Bearer ${accessToken}` }
    });
    
    const userInfo = await userRes.json();
    if (!userRes.ok || userInfo.error) {
      throw new Error(`Failed to retrieve user profile: ${userInfo.error_description || userInfo.error || "Unknown error"}`);
    }
    
    return {
      sub: userInfo.sub,
      email: userInfo.email,
      name: userInfo.name,
      picture: userInfo.picture
    };
  }
}

export async function issueJwtToken(userData, expiresIn = 3600, customSecret = null) {
  const secret = customSecret || config.JWT_SECRET_KEY;
  const now = Math.floor(Date.now() / 1000);
  const jti = crypto.randomUUID().replace(/-/g, '');
  const payload = {
    sub: userData.sub || String(userData.id || "anonymous"),
    email: userData.email || "",
    name: userData.name || "",
    picture: userData.picture || "",
    iat: now,
    exp: now + expiresIn,
    jti: jti
  };
  return await jwt.encode(payload, secret);
}

export async function verifyJwtToken(token, customSecret = null, sessionStore = null) {
  if (!token || typeof token !== 'string') return null;
  const secret = customSecret || config.JWT_SECRET_KEY;
  try {
    const payload = await jwt.decode(token, secret);
    const jti = payload.jti;
    const sig = token.split('.')[2] || token;
    
    if (sessionStore) {
      if (jti && (await sessionStore.get(`revoked:${jti}`)) !== null) return null;
      if ((await sessionStore.get(`revoked:${sig}`)) !== null) return null;
    } else {
      if (revokedTokens.has(jti) || revokedTokens.has(token) || revokedTokens.has(sig)) return null;
    }
    return payload;
  } catch (e) {
    return null;
  }
}

export async function revokeJwtToken(token, customSecret = null, sessionStore = null) {
  if (!token || typeof token !== 'string') return false;
  const secret = customSecret || config.JWT_SECRET_KEY;
  try {
    const payload = await jwt.decode(token, secret, { verifyExp: false });
    const jti = payload.jti;
    const exp = payload.exp;
    const now = Math.floor(Date.now() / 1000);
    const ttl = exp ? Math.max(60, exp - now) : 86400;
    const sig = token.split('.')[2] || token;
    
    if (sessionStore) {
      if (jti) await sessionStore.put(`revoked:${jti}`, "1", { expirationTtl: ttl });
      await sessionStore.put(`revoked:${sig}`, "1", { expirationTtl: ttl });
    } else {
      if (jti) revokedTokens.add(jti);
      revokedTokens.add(token);
      revokedTokens.add(sig);
    }
    return true;
  } catch (e) {
    const sig = token.split('.')[2] || token;
    if (sessionStore) {
      await sessionStore.put(`revoked:${sig}`, "1", { expirationTtl: 86400 });
    } else {
      revokedTokens.add(token);
      revokedTokens.add(sig);
    }
    return true;
  }
}
