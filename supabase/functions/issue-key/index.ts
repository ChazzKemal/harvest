// Hands a signed-in person their own key for the gateway. Deploy with:
//   supabase functions deploy issue-key
//
// The caller proves who they are with their own sign-in token, so this knows
// exactly who is asking. That is what makes per-person metering and revoking
// possible — a key baked into the app gives you neither.
//
// Never a real OpenAI key. That lives only on the gateway (gateway/, a
// Cloudflare Worker); what this hands out is a personal gateway key that works
// nowhere else, with a monthly budget, and is revoked on its own. Only its
// sha256 is stored, so the key exists on the person's machine and nowhere
// else. Each call makes a new key; earlier ones (other machines) keep working.
//
// Default-deny. Signing in is not enough: a key is only issued when the
// person's email is in allowed_emails. Anyone else — any Google account in the
// world can sign in — gets 403. Approve someone with:
//   insert into allowed_emails (email) values ('person@company.com');
// Deleting that row takes them out again: the gateway checks it on every
// request, not only here.

import { createClient } from "jsr:@supabase/supabase-js@2";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

// 256 random bits. The prefix makes a Cumulate key recognisable at a glance.
function newKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return "cum_" + [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function sha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async (req) => {
  const auth = req.headers.get("Authorization") ?? "";
  if (!auth.startsWith("Bearer ")) {
    return json({ error: "sign in first" }, 401);
  }

  // Supabase reserves the SUPABASE_ prefix and injects these itself, so the
  // secret cannot be set by hand under that name. Take whichever is present.
  const secret = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")
              ?? Deno.env.get("SB_SECRET_KEY")
              ?? Deno.env.get("SUPABASE_SECRET_KEY");
  if (!secret) {
    return json({ error: "not configured" }, 503);
  }
  const admin = createClient(Deno.env.get("SUPABASE_URL")!, secret);

  const { data: { user }, error } = await admin.auth.getUser(auth.slice(7));
  if (error || !user) {
    return json({ error: "sign in first" }, 401);
  }

  const email = (user.email ?? "").toLowerCase();
  const { data: allowed } = await admin
    .from("allowed_emails").select("email").eq("email", email).maybeSingle();
  if (!email || !allowed) {
    return json({ error: "no access" }, 403);
  }

  // A new key per sign-in, so each machine someone uses has its own and none
  // cuts off another. Budget and spend are per person, across all of them.
  const key = newKey();
  const { error: saveError } = await admin
    .from("gateway_keys").insert({ key_hash: await sha256(key), engineer: user.id, email });
  if (saveError) {
    return json({ error: "could not issue key" }, 500);
  }

  // Who collected a key and when.
  await admin.from("key_issues").insert({ engineer: user.id });

  return json({ key });
});
