// The gateway: everyone's Codex talks to OpenAI through this, never directly.
// A Cloudflare Worker - nothing to host, nothing that sleeps. See README.md.
//
//   Codex ── personal key ──▶ here ── the real key ──▶ OpenAI
//                              ├─ key live, email still approved, under budget?
//                              └─ afterwards: tokens and cost, per person
//
// The real OpenAI key is a secret of this Worker and never leaves it. The
// personal keys are issued by Supabase's issue-key function; this only ever
// sees their sha256, which is all Supabase keeps. Prompts and answers stream
// straight through and are never stored - only who used how much.

export interface Env {
  OPENAI_API_KEY: string;       // secret: the real key
  SUPABASE_SECRET_KEY: string;  // secret: reads keys, writes usage
  SUPABASE_URL: string;
  MONTHLY_BUDGET_USD?: string;  // everyone's default; gateway_budgets overrides per person
  ALLOWED_MODELS?: string;      // comma-separated; empty allows any
  PRICES?: string | Record<string, Price>; // {"model": {"input": .., "cached_input": .., "output": ..}}, USD per 1M tokens
  OPENAI_BASE_URL?: string;     // only for tests
}

interface Ctx {
  waitUntil(p: Promise<unknown>): void;
}

type Who = { engineer: string; email: string; spent: number; budget: number | null };
// USD per 1M tokens. `long`: a request with more input tokens than `above` is
// priced whole at `input`x and `output`x the usual rates (OpenAI's long-context
// meter).
type Price = {
  input: number;
  cached_input?: number;
  output: number;
  long?: { above: number; input: number; output: number };
};
type Usage = {
  input_tokens?: number;
  output_tokens?: number;
  input_tokens_details?: { cached_tokens?: number };
};

const OPENAI = "https://api.openai.com";

// What Codex may reach. Anything else is refused rather than passed on.
const ROUTES: [method: string, path: RegExp][] = [
  ["POST", /^\/v1\/responses(\/compact)?$/],
  ["GET", /^\/v1\/models(\/[\w.:-]+)?$/],
];

// Request headers never passed on: the person's own key, anything that would
// let a request pick another OpenAI organisation or project, and hop headers.
const DROP_REQUEST = /^(authorization|host|content-length|cookie|accept-encoding|cf-.*|x-forwarded-.*|x-real-ip|cdn-loop|openai-organization|openai-project|chatgpt-account-id)$/i;
// Response headers the body no longer matches once it has been re-streamed.
const DROP_RESPONSE = /^(content-encoding|content-length|set-cookie|transfer-encoding)$/i;

// A key's decision is remembered briefly, so a busy session does not ask
// Supabase on every request. Short enough that a removal bites within a minute.
const CACHE_MS = 30_000;
const cache = new Map<string, { who: Who | null; until: number }>();

function error(status: number, message: string, code = "cumulate_gateway"): Response {
  return new Response(JSON.stringify({ error: { message, type: "invalid_request_error", code } }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function sha256(text: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// New-style Supabase secret keys go in apikey only; legacy JWT keys in both.
function supabaseHeaders(env: Env): Record<string, string> {
  const h: Record<string, string> = { apikey: env.SUPABASE_SECRET_KEY, "Content-Type": "application/json" };
  if (env.SUPABASE_SECRET_KEY.startsWith("eyJ")) h.Authorization = `Bearer ${env.SUPABASE_SECRET_KEY}`;
  return h;
}

// Who holds this key - or null: unknown, revoked, or no longer approved.
// Throws when Supabase cannot answer, so nothing gets through unchecked.
async function lookup(env: Env, keyHash: string): Promise<Who | null> {
  const hit = cache.get(keyHash);
  if (hit && hit.until > Date.now()) return hit.who;
  const r = await fetch(`${env.SUPABASE_URL}/rest/v1/rpc/gateway_check`, {
    method: "POST",
    headers: supabaseHeaders(env),
    body: JSON.stringify({ p_key_hash: keyHash }),
  });
  if (!r.ok) throw new Error(`gateway_check ${r.status}`);
  const [row] = await r.json() as { engineer: string; email: string; spent_usd: number | string; budget_usd: number | string | null }[];
  const who = row
    ? {
      engineer: row.engineer,
      email: row.email,
      spent: Number(row.spent_usd) || 0,
      budget: row.budget_usd === null ? null : Number(row.budget_usd),
    }
    : null;
  cache.set(keyHash, { who, until: Date.now() + CACHE_MS });
  return who;
}

function prices(env: Env): Record<string, Price> {
  // wrangler.toml can give it as a JSON string or as a table.
  if (env.PRICES && typeof env.PRICES === "object") return env.PRICES;
  try {
    return env.PRICES ? JSON.parse(env.PRICES) : {};
  } catch {
    return {};
  }
}

// Exact name first, then the longest configured name it starts with, so a
// dated snapshot ("gpt-x-2026-05-01") is priced like its family ("gpt-x").
function priceFor(table: Record<string, Price>, model: string): Price | undefined {
  if (table[model]) return table[model];
  const family = Object.keys(table).filter((m) => model.startsWith(m)).sort((a, b) => b.length - a.length)[0];
  return family ? table[family] : undefined;
}

function cost(p: Price, u: Usage): number {
  const input = u.input_tokens ?? 0;
  const cached = u.input_tokens_details?.cached_tokens ?? 0;
  const output = u.output_tokens ?? 0;
  const long = p.long && input > p.long.above ? p.long : { input: 1, output: 1 };
  return (((input - cached) * p.input + cached * (p.cached_input ?? p.input)) * long.input +
    output * p.output * long.output) / 1e6;
}

async function record(env: Env, who: Who, keyHash: string, model: string, u: Usage): Promise<void> {
  const table = prices(env);
  // A model with no price is charged at the dearest one configured: better to
  // stop someone early than to let spending go uncounted.
  const price = priceFor(table, model) ??
    Object.values(table).sort((a, b) => b.output - a.output)[0];
  const row = {
    engineer: who.engineer,
    model,
    input_tokens: u.input_tokens ?? 0,
    cached_tokens: u.input_tokens_details?.cached_tokens ?? 0,
    output_tokens: u.output_tokens ?? 0,
    cost_usd: price ? Number(cost(price, u).toFixed(6)) : null,
  };
  await fetch(`${env.SUPABASE_URL}/rest/v1/gateway_usage`, {
    method: "POST",
    headers: { ...supabaseHeaders(env), Prefer: "return=minimal" },
    body: JSON.stringify(row),
  }).catch(() => {});
  // What was just spent counts towards the next request's budget check, even
  // while the cached decision is still in use.
  const hit = cache.get(keyHash);
  if (hit?.who && row.cost_usd) hit.who.spent += row.cost_usd;
}

// Passes the stream through untouched, and picks the usage out of the final
// event ("response.completed" and friends carry it) on the way past. `done`
// gets it at the end - or null, for a stream that ended without any.
function usageTap(
  done: (found: { model: string; usage: Usage } | null) => void,
): TransformStream<Uint8Array, Uint8Array> {
  const decoder = new TextDecoder();
  let buf = "";
  let found: { model: string; usage: Usage } | null = null;
  const inspect = (block: string) => {
    if (!block.includes('"usage"')) return;
    for (const line of block.split("\n")) {
      if (!line.startsWith("data:")) continue;
      try {
        const d = JSON.parse(line.slice(5));
        const r = d.response ?? d;
        if (r?.usage) found = { model: r.model ?? "", usage: r.usage };
      } catch { /* not JSON: nothing to take */ }
    }
  };
  return new TransformStream({
    transform(chunk, ctl) {
      ctl.enqueue(chunk);
      buf += decoder.decode(chunk, { stream: true }).replaceAll("\r\n", "\n");
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        inspect(buf.slice(0, i));
        buf = buf.slice(i + 2);
      }
    },
    flush() {
      buf += decoder.decode();
      if (buf.trim()) inspect(buf);
      done(found);
    },
  });
}

export default {
  async fetch(req: Request, env: Env, ctx: Ctx): Promise<Response> {
    const url = new URL(req.url);
    if (req.method === "GET" && url.pathname === "/") {
      return new Response("Cumulate gateway\n");
    }
    if (!ROUTES.some(([m, p]) => m === req.method && p.test(url.pathname))) {
      return error(404, "Not found.");
    }

    const auth = req.headers.get("Authorization") ?? "";
    const key = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
    if (!key) return error(401, "No key. Start Cumulate again to sign in.", "invalid_api_key");

    const keyHash = await sha256(key);
    let who: Who | null;
    try {
      who = await lookup(env, keyHash);
    } catch {
      return error(502, "The gateway cannot check keys right now. Try again in a moment.");
    }
    if (!who) {
      return error(401, "This key is not valid any more. Start Cumulate again to get a new one.", "invalid_api_key");
    }

    const body = req.method === "POST" ? await req.text() : undefined;
    let model = "";
    if (body) {
      // The top-level model, without parsing what can be megabytes of
      // conversation. What is charged comes from the response, not from this.
      model = /"model"\s*:\s*"([^"]+)"/.exec(body)?.[1] ?? "";
      const allowed = (env.ALLOWED_MODELS ?? "").split(",").map((m) => m.trim()).filter(Boolean);
      if (allowed.length && !allowed.includes(model)) {
        return error(403, `The model "${model}" is not available through Cumulate.`);
      }
      const budget = who.budget ?? Number(env.MONTHLY_BUDGET_USD ?? 0);
      if (budget > 0) {
        if (!priceFor(prices(env), model)) {
          return error(400, `No price is set for "${model}" on the gateway, so its spending cannot be counted. Ask whoever runs Cumulate.`);
        }
        if (who.spent >= budget) {
          return error(403, `Your Cumulate budget for this month ($${budget}) is used up. Ask whoever runs Cumulate to raise it.`, "budget_exceeded");
        }
      }
    }

    const headers = new Headers();
    for (const [k, v] of req.headers) if (!DROP_REQUEST.test(k)) headers.set(k, v);
    headers.set("Authorization", `Bearer ${env.OPENAI_API_KEY}`);

    let upstream: Response;
    try {
      upstream = await fetch(`${env.OPENAI_BASE_URL ?? OPENAI}${url.pathname}${url.search}`, {
        method: req.method,
        headers,
        body,
      });
    } catch {
      return error(502, "OpenAI could not be reached. Try again in a moment.");
    }

    const out = new Headers();
    for (const [k, v] of upstream.headers) if (!DROP_RESPONSE.test(k)) out.set(k, v);

    if (!upstream.body || req.method !== "POST") {
      return new Response(upstream.body, { status: upstream.status, headers: out });
    }

    if ((upstream.headers.get("Content-Type") ?? "").includes("text/event-stream")) {
      const person = who;
      let streamed!: ReadableStream<Uint8Array>;
      // Recorded after the last byte, without holding the answer up. A stream
      // that ends without usage (cut off, failed) records nothing.
      const recorded = new Promise<void>((resolve) => {
        const tap = usageTap((found) =>
          resolve(found ? record(env, person, keyHash, found.model || model, found.usage) : undefined)
        );
        streamed = upstream.body!.pipeThrough(tap);
      });
      ctx.waitUntil(recorded);
      return new Response(streamed, { status: upstream.status, headers: out });
    }

    const text = await upstream.text();
    try {
      const r = JSON.parse(text);
      if (r?.usage) ctx.waitUntil(record(env, who, keyHash, r.model ?? model, r.usage));
    } catch { /* an error body: nothing to record */ }
    return new Response(text, { status: upstream.status, headers: out });
  },
};
