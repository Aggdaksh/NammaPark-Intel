import { createHmac, timingSafeEqual } from "node:crypto";

const DEFAULT_MAX_AGE_SECONDS = 8 * 60 * 60;

function base64url(input) {
  return Buffer.from(input).toString("base64url");
}

function safeEqual(left, right) {
  const leftBuffer = Buffer.from(String(left));
  const rightBuffer = Buffer.from(String(right));
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer);
}

function parseCookies(header = "") {
  return Object.fromEntries(
    String(header)
      .split(";")
      .map((item) => item.trim())
      .filter(Boolean)
      .map((item) => {
        const [key, ...rest] = item.split("=");
        return [decodeURIComponent(key), decodeURIComponent(rest.join("="))];
      })
  );
}

export function createAuth({
  username = process.env.NAMMAPARK_DEMO_USER || process.env.CURBCLEAR_DEMO_USER || "operator",
  password = process.env.NAMMAPARK_DEMO_PASSWORD || process.env.CURBCLEAR_DEMO_PASSWORD || "gridlock",
  secret = process.env.NAMMAPARK_AUTH_SECRET || process.env.CURBCLEAR_AUTH_SECRET || "nammapark-local-demo-secret",
  cookieName = "cc_session",
  maxAgeSeconds = DEFAULT_MAX_AGE_SECONDS,
  users = null
} = {}) {
  const demoUsers =
    users ||
    [
      { username, password, role: "operator", label: "Operator" },
      {
        username: process.env.NAMMAPARK_ADMIN_USER || "admin",
        password: process.env.NAMMAPARK_ADMIN_PASSWORD || "admin123",
        role: "admin",
        label: "Administrator"
      },
      {
        username: process.env.NAMMAPARK_VIEWER_USER || "viewer",
        password: process.env.NAMMAPARK_VIEWER_PASSWORD || "viewer123",
        role: "viewer",
        label: "Viewer"
      }
    ];

  function findUser(candidateUser) {
    return demoUsers.find((item) => safeEqual(candidateUser, item.username));
  }

  function sign(payload) {
    return createHmac("sha256", secret).update(payload).digest("base64url");
  }

  function createToken(user) {
    const now = Math.floor(Date.now() / 1000);
    const account = findUser(user) || { username: user, role: "operator", label: "Operator" };
    const payload = base64url(
      JSON.stringify({
        sub: account.username,
        role: account.role,
        label: account.label,
        iat: now,
        exp: now + maxAgeSeconds
      })
    );
    return `${payload}.${sign(payload)}`;
  }

  function verifyToken(token) {
    const [payload, signature] = String(token || "").split(".");
    if (!payload || !signature || !safeEqual(sign(payload), signature)) {
      return null;
    }
    try {
      const session = JSON.parse(Buffer.from(payload, "base64url").toString("utf-8"));
      if (!session.sub || Number(session.exp || 0) < Math.floor(Date.now() / 1000)) {
        return null;
      }
      return {
        username: String(session.sub),
        role: String(session.role || "operator"),
        label: String(session.label || "Operator"),
        expires_at: Number(session.exp)
      };
    } catch {
      return null;
    }
  }

  function sessionFromRequest(req) {
    const cookies = parseCookies(req.headers.cookie || "");
    return verifyToken(cookies[cookieName]);
  }

  function isAuthenticated(req) {
    return Boolean(sessionFromRequest(req));
  }

  function validateCredentials(candidateUser, candidatePassword) {
    const account = findUser(candidateUser);
    return Boolean(account) && safeEqual(candidatePassword, account.password);
  }

  function loginHeaders(user) {
    const token = createToken(user);
    return {
      "set-cookie": `${cookieName}=${encodeURIComponent(token)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${maxAgeSeconds}`
    };
  }

  function logoutHeaders() {
    return {
      "set-cookie": `${cookieName}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0`
    };
  }

  return {
    username,
    users: demoUsers.map(({ username: user, role, label }) => ({ username: user, role, label })),
    cookieName,
    maxAgeSeconds,
    isAuthenticated,
    sessionFromRequest,
    validateCredentials,
    loginHeaders,
    logoutHeaders
  };
}
