// Tests for the issue-key function's decision logic, with the Supabase client
// replaced by ./mock_supabase.ts (see deno.json). Run from this directory:
//   deno test --allow-env --allow-read --config deno.json .
import { assertEquals } from "jsr:@std/assert";
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
Deno.env.set("FALLBACK_OPENAI_KEY", "sk-shared-fallback");

await import("../issue-key/index.ts");

function call(withBearer = true) {
  return handler(
    new Request("http://localhost/issue-key", {
      headers: withBearer ? { Authorization: "Bearer token123" } : {},
    }),
  );
}

Deno.test("no bearer token -> 401", async () => {
  const res = await call(false);
  assertEquals(res.status, 401);
});

Deno.test("invalid token -> 401", async () => {
  scenario.user = null;
  const res = await call();
  assertEquals(res.status, 401);
});

Deno.test("signed in, NOT approved -> 403, no key, nothing logged", async () => {
  scenario.user = { id: "u1", email: "stranger@gmail.com" };
  scenario.apiKeyRow = null;
  scenario.allowedRow = null;
  scenario.issues.length = 0;
  const res = await call();
  assertEquals(res.status, 403);
  assertEquals((await res.json()).key, undefined);
  assertEquals(scenario.issues.length, 0);
});

Deno.test("signed in, email approved -> 200 with shared key", async () => {
  scenario.user = { id: "u2", email: "Approved@Company.com" };
  scenario.apiKeyRow = null;
  scenario.allowedRow = { email: "approved@company.com" };
  scenario.issues.length = 0;
  const res = await call();
  assertEquals(res.status, 200);
  assertEquals((await res.json()).key, "sk-shared-fallback");
  assertEquals(scenario.issues.length, 1);
});

Deno.test("personal key wins even without allowlist entry", async () => {
  scenario.user = { id: "u3", email: "own@key.com" };
  scenario.apiKeyRow = { key: "sk-personal", revoked: false };
  scenario.allowedRow = null;
  const res = await call();
  assertEquals(res.status, 200);
  assertEquals((await res.json()).key, "sk-personal");
});

Deno.test("revoked personal row -> 403 even if email allowed", async () => {
  scenario.user = { id: "u4", email: "revoked@company.com" };
  scenario.apiKeyRow = { key: "sk-old", revoked: true };
  scenario.allowedRow = { email: "revoked@company.com" };
  const res = await call();
  assertEquals(res.status, 403);
});

Deno.test("user with no email -> 403", async () => {
  scenario.user = { id: "u5", email: null };
  scenario.apiKeyRow = null;
  scenario.allowedRow = null;
  const res = await call();
  assertEquals(res.status, 403);
});

Deno.test("approved but fallback key unset -> 503", async () => {
  Deno.env.delete("FALLBACK_OPENAI_KEY");
  scenario.user = { id: "u6", email: "approved@company.com" };
  scenario.apiKeyRow = null;
  scenario.allowedRow = { email: "approved@company.com" };
  const res = await call();
  assertEquals(res.status, 503);
  Deno.env.set("FALLBACK_OPENAI_KEY", "sk-shared-fallback");
});
