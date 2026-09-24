// Tests for the gateway Worker, with Supabase and OpenAI replaced by a fake
// fetch. Run from this folder:
//   deno test worker.test.ts
import { assert, assertEquals } from "jsr:@std/assert";
import worker, { type Env } from "./worker.ts";

const SUPABASE = "https://db.example";
const OPENAI = "https://openai.example";

const env = (extra: Partial<Env> = {}): Env => ({
  OPENAI_API_KEY: "sk-REAL-openai-key",
  SUPABASE_SECRET_KEY: "sb_secret_test",
  SUPABASE_URL: SUPABASE,
  OPENAI_BASE_URL: OPENAI,
  MONTHLY_BUDGET_USD: "20",
  PRICES: JSON.stringify({ "gpt-test": { input: 1, cached_input: 0.1, output: 10 } }),
  ...extra,
});

// --- the fakes ----------------------------------------------------------------

type Seen = { url: string; method: string; headers: Headers; body: string };
let seen: Seen[] = [];
let people: Record<string, { engineer: string; email: string; spent_usd: number; budget_usd: number | null }> = {};
let openai: (req: Seen) => Response = () => new Response("{}");
let supabaseDown = false;

async function sha256(text: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

globalThis.fetch = async (input: string | URL | Request, init?: RequestInit) => {
  const s: Seen = {
    url: String(input),
    method: init?.method ?? "GET",
    headers: new Headers(init?.headers),
    body: typeof init?.body === "string" ? init.body : "",
  };
  seen.push(s);
  if (s.url.startsWith(SUPABASE)) {
    if (supabaseDown) return new Response("down", { status: 503 });
    if (s.url.endsWith("/rpc/gateway_check")) {
      const { p_key_hash } = JSON.parse(s.body);
      const row = people[p_key_hash];
      return new Response(JSON.stringify(row ? [row] : []));
    }
    return new Response(null, { status: 201 });
  }
  return openai(s);
};

const ctxFor = () => {
  const pending: Promise<unknown>[] = [];
  return { ctx: { waitUntil: (p: Promise<unknown>) => void pending.push(p) }, settle: () => Promise.all(pending) };
};

let n = 0;
// A fresh person with their own key, so the Worker's short cache never mixes tests.
async function person(opts: { spent?: number; budget?: number | null } = {}) {
  const key = `cum_test_${++n}`;
  people[await sha256(key)] = {
    engineer: `u${n}`,
    email: `eng${n}@company.com`,
    spent_usd: opts.spent ?? 0,
    budget_usd: opts.budget ?? null,
  };
  return { key, engineer: `u${n}` };
}

function reset() {
  seen = [];
  supabaseDown = false;
  openai = () => new Response("{}");
}

const request = (key: string | null, body: unknown = { model: "gpt-test", input: "hi", stream: true }, path = "/v1/responses", extraHeaders: Record<string, string> = {}) =>
  new Request(`https://gateway.example${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(key ? { Authorization: `Bearer ${key}` } : {}), ...extraHeaders },
    body: JSON.stringify(body),
  });

// An SSE stream as OpenAI sends it, cut into awkward chunks - including one
// that splits the final event in two.
function sse(model: string, usage: unknown): Response {
  const text = [
    `event: response.created\ndata: {"type":"response.created","response":{"model":"${model}","usage":null}}\n\n`,
    `event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"Hel"}\n\n`,
    `event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"lo"}\n\n`,
    `event: response.completed\ndata: {"type":"response.completed","response":{"model":"${model}","usage":${JSON.stringify(usage)}}}\n\n`,
  ].join("");
  const bytes = new TextEncoder().encode(text);
  const cuts = [0, 17, 90, bytes.length - 40, bytes.length];
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      for (let i = 0; i < cuts.length - 1; i++) c.enqueue(bytes.slice(cuts[i], cuts[i + 1]));
      c.close();
    },
  });
  return new Response(body, {
    headers: { "Content-Type": "text/event-stream", "Content-Encoding": "gzip", "x-request-id": "req_1" },
  });
}

const usageRows = () =>
  seen.filter((s) => s.url.endsWith("/rest/v1/gateway_usage")).map((s) => JSON.parse(s.body));
const openaiCalls = () => seen.filter((s) => s.url.startsWith(OPENAI));

// --- tests --------------------------------------------------------------------

Deno.test("health check answers without a key", async () => {
  reset();
  const res = await worker.fetch(new Request("https://gateway.example/"), env(), ctxFor().ctx);
  assertEquals(res.status, 200);
});

Deno.test("anything but Codex's endpoints -> 404, OpenAI never called", async () => {
  reset();
  const { key } = await person();
  for (const path of ["/v1/files", "/v1/chat/completions", "/v1/responses/../files", "/admin"]) {
    const res = await worker.fetch(request(key, {}, path), env(), ctxFor().ctx);
    assertEquals(res.status, 404, path);
  }
  assertEquals(openaiCalls().length, 0);
});

Deno.test("no key -> 401", async () => {
  reset();
  const res = await worker.fetch(request(null), env(), ctxFor().ctx);
  assertEquals(res.status, 401);
  assertEquals(openaiCalls().length, 0);
});

Deno.test("unknown, revoked or unapproved key -> 401, OpenAI never called", async () => {
  reset();
  const res = await worker.fetch(request("cum_nobody"), env(), ctxFor().ctx);
  assertEquals(res.status, 401);
  assertEquals(openaiCalls().length, 0);
});

Deno.test("Supabase down -> 502: nothing gets through unchecked", async () => {
  reset();
  supabaseDown = true;
  const res = await worker.fetch(request("cum_whoever"), env(), ctxFor().ctx);
  assertEquals(res.status, 502);
  assertEquals(openaiCalls().length, 0);
});

Deno.test("streams through byte for byte; real key swapped in; person's key never sent on", async () => {
  reset();
  const { key, engineer } = await person();
  const upstream = sse("gpt-test", { input_tokens: 1000, output_tokens: 100, input_tokens_details: { cached_tokens: 400 } });
  const expected = await upstream.clone().text();
  openai = () => upstream;
  const { ctx, settle } = ctxFor();
  const res = await worker.fetch(
    request(key, undefined, "/v1/responses", { "OpenAI-Organization": "org-other", "session_id": "s1" }),
    env(), ctx);
  assertEquals(res.status, 200);
  assertEquals(await res.text(), expected);
  assertEquals(res.headers.get("content-type"), "text/event-stream");
  assertEquals(res.headers.get("x-request-id"), "req_1");
  assertEquals(res.headers.get("content-encoding"), null);

  const [call] = openaiCalls();
  assertEquals(call.url, `${OPENAI}/v1/responses`);
  assertEquals(call.headers.get("authorization"), "Bearer sk-REAL-openai-key");
  assertEquals(call.headers.get("openai-organization"), null);
  assertEquals(call.headers.get("session_id"), "s1");
  assert(!JSON.stringify([...call.headers]).includes(key));

  await settle();
  const [row] = usageRows();
  assertEquals(row.engineer, engineer);
  assertEquals(row.model, "gpt-test");
  assertEquals([row.input_tokens, row.cached_tokens, row.output_tokens], [1000, 400, 100]);
  // 600 fresh input at $1/M + 400 cached at $0.10/M + 100 output at $10/M
  assertEquals(row.cost_usd, 0.00164);
});

Deno.test("the real key never appears in anything sent back", async () => {
  reset();
  const { key } = await person();
  openai = () => sse("gpt-test", { input_tokens: 1, output_tokens: 1 });
  const res = await worker.fetch(request(key), env(), ctxFor().ctx);
  const back = (await res.text()) + JSON.stringify([...res.headers]);
  assert(!back.includes("sk-REAL-openai-key"));
});

Deno.test("priced by the model OpenAI actually ran, not the one the request claims", async () => {
  reset();
  const { key } = await person();
  openai = () => sse("gpt-test-2026-05-01", { input_tokens: 1_000_000, output_tokens: 0 });
  const { ctx, settle } = ctxFor();
  await (await worker.fetch(request(key, { model: "gpt-test", stream: true }), env(), ctx)).text();
  await settle();
  const [row] = usageRows();
  assertEquals(row.model, "gpt-test-2026-05-01");
  assertEquals(row.cost_usd, 1); // family price, found by prefix
});

Deno.test("a very long request is priced at the long-context rates", async () => {
  reset();
  const { key } = await person();
  openai = () => sse("gpt-long", { input_tokens: 300_000, output_tokens: 10_000 });
  const { ctx, settle } = ctxFor();
  const e = env({
    PRICES: JSON.stringify({ "gpt-long": { input: 10, output: 50, long: { above: 272_000, input: 2, output: 1.5 } } }),
  });
  await (await worker.fetch(request(key, { model: "gpt-long", stream: true }), e, ctx)).text();
  await settle();
  // 300k input at $20/M = $6, 10k output at $75/M = $0.75
  assertEquals(usageRows()[0].cost_usd, 6.75);
});

Deno.test("a model with no price is charged at the dearest price, never for free", async () => {
  reset();
  const { key } = await person();
  openai = () => sse("something-else", { input_tokens: 0, output_tokens: 1_000_000 });
  const { ctx, settle } = ctxFor();
  await (await worker.fetch(request(key), env(), ctx)).text();
  await settle();
  assertEquals(usageRows()[0].cost_usd, 10);
});

Deno.test("over budget -> 403 with a clear message, OpenAI never called", async () => {
  reset();
  const { key } = await person({ spent: 20 });
  const res = await worker.fetch(request(key), env(), ctxFor().ctx);
  assertEquals(res.status, 403);
  assert((await res.json()).error.message.includes("budget"));
  assertEquals(openaiCalls().length, 0);
});

Deno.test("a personal budget overrides the default", async () => {
  reset();
  const { key } = await person({ spent: 25, budget: 50 });
  openai = () => sse("gpt-test", { input_tokens: 1, output_tokens: 1 });
  const res = await worker.fetch(request(key), env(), ctxFor().ctx);
  assertEquals(res.status, 200);
  await res.text();
});

Deno.test("spending counts at once, even while the key's check is cached", async () => {
  reset();
  const { key } = await person({ spent: 19.5 });
  // One response costing $1 takes them from 19.50 to 20.50 - over the $20 budget.
  openai = () => sse("gpt-test", { input_tokens: 0, output_tokens: 100_000 });
  const first = ctxFor();
  await (await worker.fetch(request(key), env(), first.ctx)).text();
  await first.settle();
  const res = await worker.fetch(request(key), env(), ctxFor().ctx);
  assertEquals(res.status, 403);
});

Deno.test("with a budget, a model with no price is refused up front, saying what to pick", async () => {
  reset();
  const { key } = await person();
  const res = await worker.fetch(request(key, { model: "unpriced", stream: true }), env(), ctxFor().ctx);
  assertEquals(res.status, 403);
  const { message } = (await res.json()).error;
  assert(message.includes('"unpriced" is not available'), message);
  assert(message.includes("/model and choose gpt-test"), message);
  assertEquals(openaiCalls().length, 0);
});

Deno.test("ALLOWED_MODELS refuses anything else, and names what is allowed", async () => {
  reset();
  const { key } = await person();
  const res = await worker.fetch(
    request(key, { model: "gpt-expensive", stream: true }),
    env({ ALLOWED_MODELS: "gpt-test" }), ctxFor().ctx);
  assertEquals(res.status, 403);
  const { message, code } = (await res.json()).error;
  assertEquals(code, "model_not_available");
  assert(message.includes("Type /model and choose gpt-test."), message);
  assertEquals(openaiCalls().length, 0);
});

Deno.test("an allowed model is let through", async () => {
  reset();
  const { key } = await person();
  openai = () => sse("gpt-test", { input_tokens: 1, output_tokens: 1 });
  const res = await worker.fetch(request(key), env({ ALLOWED_MODELS: "gpt-test" }), ctxFor().ctx);
  assertEquals(res.status, 200);
  await res.text();
});

Deno.test("a non-streamed response is recorded too", async () => {
  reset();
  const { key } = await person();
  openai = () =>
    new Response(JSON.stringify({ model: "gpt-test", usage: { input_tokens: 10, output_tokens: 20 } }), {
      headers: { "Content-Type": "application/json" },
    });
  const { ctx, settle } = ctxFor();
  const res = await worker.fetch(request(key, { model: "gpt-test" }), env(), ctx);
  assertEquals(res.status, 200);
  await settle();
  assertEquals(usageRows()[0].output_tokens, 20);
});

Deno.test("an OpenAI error is passed back as is, and nothing recorded", async () => {
  reset();
  const { key } = await person();
  openai = () => new Response(JSON.stringify({ error: { message: "bad request" } }), { status: 400, headers: { "Content-Type": "application/json" } });
  const { ctx, settle } = ctxFor();
  const res = await worker.fetch(request(key), env(), ctx);
  assertEquals(res.status, 400);
  assertEquals((await res.json()).error.message, "bad request");
  await settle();
  assertEquals(usageRows().length, 0);
});

Deno.test("GET /v1/models passes through, key still required", async () => {
  reset();
  const { key } = await person();
  openai = () => new Response(JSON.stringify({ data: [] }), { headers: { "Content-Type": "application/json" } });
  const ok = await worker.fetch(
    new Request("https://gateway.example/v1/models", { headers: { Authorization: `Bearer ${key}` } }),
    env(), ctxFor().ctx);
  assertEquals(ok.status, 200);
  const no = await worker.fetch(new Request("https://gateway.example/v1/models"), env(), ctxFor().ctx);
  assertEquals(no.status, 401);
});
