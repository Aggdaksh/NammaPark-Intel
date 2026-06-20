import assert from "node:assert/strict";

import { createAuth } from "../backend/node/auth.js";

const auth = createAuth({
  username: "operator",
  password: "gridlock",
  secret: "test-secret",
  maxAgeSeconds: 60
});

assert.equal(auth.validateCredentials("operator", "gridlock"), true);
assert.equal(auth.validateCredentials("operator", "wrong"), false);

const headers = auth.loginHeaders("operator");
assert.ok(headers["set-cookie"].includes("cc_session="));
assert.ok(headers["set-cookie"].includes("HttpOnly"));
assert.ok(headers["set-cookie"].includes("SameSite=Lax"));

const cookie = headers["set-cookie"].split(";")[0];
const session = auth.sessionFromRequest({ headers: { cookie } });
assert.equal(session.username, "operator");
assert.equal(auth.isAuthenticated({ headers: { cookie } }), true);
assert.equal(auth.isAuthenticated({ headers: { cookie: "cc_session=bad" } }), false);

const logout = auth.logoutHeaders();
assert.ok(logout["set-cookie"].includes("Max-Age=0"));

console.log(JSON.stringify({ status: "ok", auth: "signed-cookie" }, null, 2));
