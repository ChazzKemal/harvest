// Tests for the issue-key function's decision logic, with the Supabase client
// replaced by ./mock_supabase.ts (see deno.json). Run from this directory:
//   deno test --allow-env --allow-read --config deno.json .
import { assert, assertEquals, assertNotEquals } from "jsr:@std/assert";
import { scenario } from "./mock_supabase.ts";

// Capture the handler instead of starting a server.
let handler: (req: Request) => Response | Promise<Response>;
// deno-lint-ignore no-explicit-any
(Deno as any).serve = (h: typeof handler) => {
  handler = h;
  return { finished: Promise.resolve() };
};

Deno.env.set("SUPABASE_URL", "http://localhost");
Deno.env.set("SB_SECRET_KEY", "test-secret");
// The old shared-key setting. Set on purpose: nothing may ever hand it out.
Deno.env.set("FALLBACK_OPENAI_KEY", "sk-real-shared");

await import("../issue-key/index.ts");

function reset(user: { id: string; email: string | null } | null) {
  scenario.user = user;
  scenario.allowedRow = null;
  scenario.writes.length = 0;
  scenario.failTable = null;
}

function call(withBearer = true) {
  return handler(
    new Request("http://localhost/issue-key", {
      headers: withBearer ? { Authorization: "Bearer token123" } : {},
    }),
  );
}

async function sha256(text: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

const inserts = (table: string) =>
  scenario.writes.filter((w) => w.table === table && w.op === "insert");

Deno.test("no bearer token -> 401", async () => {
  reset(null);
  assertEquals((await call(false)).status, 401);
});

Deno.test("invalid token -> 401", async () => {
  reset(null);
  assertEquals((await call()).status, 401);
});

Deno.test("signed in, NOT approved -> 403, no key, nothing written", async () => {
  reset({ id: "u1", email: "stranger@gmail.com" });
  const res = await call();
  assertEquals(res.status, 403);
  assertEquals((await res.json()).key, undefined);
  assertEquals(scenario.writes.length, 0);
});

Deno.test("user with no email -> 403", async () => {
  reset({ id: "u2", email: null });
  assertEquals((await call()).status, 403);
});

Deno.test("approved -> a new personal key; only its hash stored; never the real key", async () => {
  reset({ id: "u3", email: "Eng@Company.com" });
  scenario.allowedRow = { email: "eng@company.com" };
  const res = await call();
  assertEquals(res.status, 200);
  const { key } = await res.json();
  assert(/^cum_[0-9a-f]{64}$/.test(key), `unexpected key shape: ${key}`);
  assertNotEquals(key, "sk-real-shared");

  const [saved] = inserts("gateway_keys");
  assertEquals(saved.row, { key_hash: await sha256(key), engineer: "u3", email: "eng@company.com" });
  // The key itself is written nowhere.
  assert(!JSON.stringify(scenario.writes).includes(key));
  assertEquals(inserts("key_issues").length, 1);
});

Deno.test("issuing a new key revokes the previous one first", async () => {
  reset({ id: "u4", email: "eng@company.com" });
  scenario.allowedRow = { email: "eng@company.com" };
  await call();
  const revoke = scenario.writes.findIndex((w) => w.table === "gateway_keys" && w.op === "update");
  const save = scenario.writes.findIndex((w) => w.table === "gateway_keys" && w.op === "insert");
  assert(revoke >= 0 && revoke < save, "revoke must come before the new key");
  assertEquals(scenario.writes[revoke].row, { revoked: true });
  assertEquals(scenario.writes[revoke].where, ["engineer", "u4"]);
});

Deno.test("two calls -> two different keys", async () => {
  reset({ id: "u5", email: "eng@company.com" });
  scenario.allowedRow = { email: "eng@company.com" };
  const a = (await (await call()).json()).key;
  const b = (await (await call()).json()).key;
  assertNotEquals(a, b);
});

Deno.test("key cannot be saved -> 500, no key handed out", async () => {
  reset({ id: "u6", email: "eng@company.com" });
  scenario.allowedRow = { email: "eng@company.com" };
  scenario.failTable = "gateway_keys";
  const res = await call();
  assertEquals(res.status, 500);
  assertEquals((await res.json()).key, undefined);
  assertEquals(inserts("key_issues").length, 0);
});
