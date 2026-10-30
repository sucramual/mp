#!/usr/bin/env node
// Prints one JSON line: whether the verify-browser Chrome answers, and the state of its Okta session.
// It opens a tab on the Okta dashboard over the Chrome DevTools Protocol, reads /api/v1/sessions/me inside
// that page, and closes the tab. The page load also renews Okta's 2-hour idle timeout.
// It returns only status and timing fields: never a session ID, a token, or a cookie value.
// Exit 0 when the session is ACTIVE, 1 otherwise. Node 22 has fetch and WebSocket, so it needs no packages.
//
// Environment: VERIFY_BROWSER_OKTA_URL (required; verify-browser sets it from ~/.config/verify-browser/okta-url),
// VERIFY_BROWSER_PORT (default 9222), and VERIFY_BROWSER_SETTLE_MS (default 8000), the wait for the page.

const OKTA_URL = process.env.VERIFY_BROWSER_OKTA_URL || "";
const NO_OKTA_URL =
  "no Okta URL: set VERIFY_BROWSER_OKTA_URL, or write the URL as one line to ~/.config/verify-browser/okta-url";
const PORT = process.env.VERIFY_BROWSER_PORT || "9222";
const SETTLE_MS = Number(process.env.VERIFY_BROWSER_SETTLE_MS || 8000);
const DEADLINE_MS = 45000;
const FIELDS = ["status", "createdAt", "lastPasswordVerification", "lastFactorVerification", "expiresAt"];

const report = {
  checked_at: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
  okta_url: OKTA_URL || null,
  chrome: { answers: false },
  okta: null,
};

// An okta result for a check that never reached Okta. http_status null tells auth-helper it is an error.
function oktaError(error) {
  const out = { http_status: null, error };
  for (const field of FIELDS) out[field] = null;
  return out;
}

function oktaOrigin() {
  try {
    return new URL(OKTA_URL).origin;
  } catch {
    return null;
  }
}

function finish() {
  process.stdout.write(`${JSON.stringify(report)}\n`);
  process.exit(report.okta?.status === "ACTIVE" ? 0 : 1);
}

function message(error) {
  return String(error?.cause?.code || error?.message || error);
}

// Runs inside the Okta page, so the fetch carries the page's own session cookie. Only FIELDS leave the page.
const readSession = (origin) => `(async () => {
  const fields = ${JSON.stringify(FIELDS)};
  const out = { http_status: null, error: null };
  for (const field of fields) out[field] = null;
  if (location.origin !== ${JSON.stringify(origin)}) {
    out.error = "the Okta page landed on " + location.origin;
    return out;
  }
  try {
    const response = await fetch("/api/v1/sessions/me", { credentials: "include", headers: { Accept: "application/json" } });
    out.http_status = response.status;
    if (!response.ok) {
      out.error = "Okta answered HTTP " + response.status;
      return out;
    }
    const body = await response.json();
    for (const field of fields) out[field] = typeof body[field] === "string" ? body[field] : null;
  } catch (error) {
    out.error = String((error && error.message) || error);
  }
  return out;
})()`;

async function main() {
  const origin = oktaOrigin();
  if (!OKTA_URL) report.okta = oktaError(NO_OKTA_URL);
  else if (!origin) report.okta = oktaError(`VERIFY_BROWSER_OKTA_URL is not a URL: ${OKTA_URL}`);
  let version;
  try {
    const response = await fetch(`http://127.0.0.1:${PORT}/json/version`, { signal: AbortSignal.timeout(5000) });
    version = await response.json();
  } catch (error) {
    report.chrome = { answers: false, error: message(error) };
    return;
  }
  report.chrome = { answers: true, browser: version.Browser ?? null };
  if (!origin) return;

  const socket = new WebSocket(version.webSocketDebuggerUrl);
  const pending = new Map();
  let nextId = 0;
  socket.onmessage = (event) => {
    const reply = JSON.parse(event.data);
    const waiter = pending.get(reply.id);
    if (!waiter) return;
    pending.delete(reply.id);
    if (reply.error) waiter.reject(new Error(reply.error.message));
    else waiter.resolve(reply.result);
  };
  socket.onclose = () => {
    for (const waiter of pending.values()) waiter.reject(new Error("the DevTools connection closed"));
    pending.clear();
  };
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = () => reject(new Error("cannot open the DevTools connection"));
  });
  const send = (method, params = {}, sessionId) =>
    new Promise((resolve, reject) => {
      const id = ++nextId;
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });

  const { targetId } = await send("Target.createTarget", { url: `${origin}/app/UserHome` });
  try {
    const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
    await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));
    const { result } = await send(
      "Runtime.evaluate",
      { expression: readSession(origin), awaitPromise: true, returnByValue: true },
      sessionId,
    );
    report.okta = result?.value ?? oktaError("the page returned no result");
  } finally {
    await send("Target.closeTarget", { targetId }).catch(() => {});
    socket.close();
  }
}

setTimeout(() => {
  report.error = `timed out after ${DEADLINE_MS / 1000}s`;
  finish();
}, DEADLINE_MS);

main()
  .catch((error) => {
    report.error = message(error);
  })
  .finally(finish);
