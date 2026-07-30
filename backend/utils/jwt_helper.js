function str2ab(str) {
  return new TextEncoder().encode(str);
}

function bufferToBase64Url(buf) {
  const binstr = Array.from(new Uint8Array(buf), ch => String.fromCharCode(ch)).join('');
  const b64 = btoa(binstr);
  return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

function base64UrlDecode(str) {
  str = str.replace(/-/g, '+').replace(/_/g, '/');
  while (str.length % 4) str += '=';
  const binstr = atob(str);
  const buf = new Uint8Array(binstr.length);
  for (let i = 0; i < binstr.length; i++) {
    buf[i] = binstr.charCodeAt(i);
  }
  return buf;
}

export async function encode(payload, secret) {
  const header = { alg: "HS256", typ: "JWT" };
  const headerB64 = bufferToBase64Url(str2ab(JSON.stringify(header)));
  const payloadB64 = bufferToBase64Url(str2ab(JSON.stringify(payload)));
  const signingInput = `${headerB64}.${payloadB64}`;
  
  const key = await crypto.subtle.importKey(
    "raw",
    str2ab(secret),
    { name: "HMAC", hash: { name: "SHA-256" } },
    false,
    ["sign"]
  );
  
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    str2ab(signingInput)
  );
  
  return `${signingInput}.${bufferToBase64Url(signature)}`;
}

export async function decode(jwtStr, secret, options = {}) {
  const verifyExp = options.verifyExp !== false;
  const parts = jwtStr.split('.');
  if (parts.length !== 3) {
    throw new Error("Invalid token segments");
  }
  
  const [headerB64, payloadB64, signatureB64] = parts;
  const signingInput = `${headerB64}.${payloadB64}`;
  
  const key = await crypto.subtle.importKey(
    "raw",
    str2ab(secret),
    { name: "HMAC", hash: { name: "SHA-256" } },
    false,
    ["verify"]
  );
  
  let verified;
  try {
    verified = await crypto.subtle.verify(
      "HMAC",
      key,
      base64UrlDecode(signatureB64),
      str2ab(signingInput)
    );
  } catch (e) {
    throw new Error("Signature verification failed due to crypt error: " + e.message);
  }
  
  if (!verified) {
    throw new Error("Signature verification failed");
  }
  
  const payloadBytes = base64UrlDecode(payloadB64);
  const payload = JSON.parse(new TextDecoder().decode(payloadBytes));
  
  if (verifyExp && payload.exp) {
    if ((Date.now() / 1000) > payload.exp) {
      throw new Error("Token expired");
    }
  }
  
  return payload;
}
