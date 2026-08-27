// Hands a signed-in person their API key. Deploy with:
//   supabase functions deploy issue-key
//
// The caller proves who they are with their own sign-in token, so this knows
// exactly who is asking. That is what makes per-person metering and revoking
// possible — a key baked into the app gives you neither.
//
// Default-deny. Signing in is not enough: a key is only issued when the
// person has been approved. Two ways to answer, in order:
//   1. a row in api_keys for this person       — their own key; revoke by row
//   2. their email in allowed_emails            — the shared FALLBACK_OPENAI_KEY
// Anyone else — any Google account in the world can sign in — gets 403.
// Approve someone with:
//   insert into allowed_emails (email) values ('person@company.com');
//
// Worth knowing: handing out a real OpenAI key means it lives on that person's
// machine and they can read it. If you need spending caps you cannot be talked
// out of, put a proxy in front of the OpenAI API and hand out proxy tokens
// instead — same shape, this endpoint just returns a different string.

import { createClient } from "jsr:@supabase/supabase-js@2";

Deno.serve(async (req) => {
  const auth = req.headers.get("Authorization") ?? "";
  if (!auth.startsWith("Bearer ")) {
    return new Response(JSON.stringify({ error: "sign in first" }), { status: 401 });
  }

  // Supabase reserves the SUPABASE_ prefix and injects these itself, so the
  // secret cannot be set by hand under that name. Take whichever is present.
  const secret = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")
              ?? Deno.env.get("SB_SECRET_KEY")
              ?? Deno.env.get("SUPABASE_SECRET_KEY");
  if (!secret) {
    return new Response(JSON.stringify({ error: "not configured" }), { status: 503 });
  }
  const admin = createClient(Deno.env.get("SUPABASE_URL")!, secret);

  const { data: { user }, error } = await admin.auth.getUser(auth.slice(7));
  if (error || !user) {
    return new Response(JSON.stringify({ error: "sign in first" }), { status: 401 });
  }

  const { data: row } = await admin
    .from("api_keys").select("key, revoked").eq("engineer", user.id).maybeSingle();

  if (row?.revoked) {
    return new Response(JSON.stringify({ error: "no access" }), { status: 403 });
  }

  let key = row?.key;
  if (!key) {
    // No personal key: the shared one, and only for approved emails.
    const email = (user.email ?? "").toLowerCase();
    const { data: allowed } = await admin
      .from("allowed_emails").select("email").eq("email", email).maybeSingle();
    if (!email || !allowed) {
      return new Response(JSON.stringify({ error: "no access" }), { status: 403 });
    }
    key = Deno.env.get("FALLBACK_OPENAI_KEY");
  }
  if (!key) {
    return new Response(JSON.stringify({ error: "no key available" }), { status: 503 });
  }

  // Who collected a key and when — the only record you get, since the key
  // itself leaves the building after this.
  await admin.from("key_issues").insert({ engineer: user.id });

  return new Response(JSON.stringify({ key }), {
    headers: { "Content-Type": "application/json" },
  });
});
