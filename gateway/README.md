# The gateway

A small Cloudflare Worker between everyone's Codex and OpenAI. Free, nothing
to host, nothing that sleeps.

    Engineer's Codex ── personal key ──▶ gateway ── real key ──▶ OpenAI
                                           ├─ key live? email still approved? under budget?
                                           └─ afterwards: tokens and cost, per person (in Supabase)

- **Your OpenAI key lives only here**, as a Worker secret. Engineers never see it.
- **Each engineer has their own key**, issued by Supabase's `issue-key` when they
  sign in. It works nowhere but here. Supabase keeps only its sha256.
- **Budgets:** a monthly limit per person, in USD.
- **Removing someone** is deleting their row in `allowed_emails`. It takes effect
  within 30 seconds.
- **Prompts and answers stream straight through and are never stored.** Only who
  used how many tokens, and what that cost.

Cloudflare's free plan allows 100,000 requests a day, far more than a small team
uses. The time spent waiting on OpenAI doesn't count against its limits.

## Set it up (once, about 15 minutes)

You need a free Cloudflare account (no card) and Node.js on your own machine.
Do these in order.

**1. The tables.** Supabase dashboard → SQL Editor → paste all of
`supabase/schema.sql` → Run. It's safe to re-run and adds the gateway's tables
next to the existing ones.

**2. The Worker.** From this folder:

    npx wrangler login                              # opens the browser, once
    npx wrangler secret put OPENAI_API_KEY          # paste your OpenAI key
    npx wrangler secret put SUPABASE_SECRET_KEY     # Supabase → Project Settings → API Keys → secret key

Check `wrangler.toml`. In particular, compare the budget (`MONTHLY_BUDGET_USD`) and
the prices (`PRICES`) against openai.com/api/pricing. Then:

    npx wrangler deploy

It prints the gateway's address, like
`https://cumulate-gateway.<your-name>.workers.dev`. Opening it in a browser
should show `Cumulate gateway`.

**3. The key-issuing function.** From the Harvest folder:

    supabase functions deploy issue-key

It hands out only gateway keys from now on, never an OpenAI key.

**4. Switch Cumulate over.** In the cumulate repo's `config.env`, set (no
trailing slash):

    CUMULATE_GATEWAY=https://cumulate-gateway.<your-name>.workers.dev
    CUMULATE_MODEL=<a model from PRICES>

Commit and push. At their next start, everyone is issued a personal key
automatically. Their sign-in is remembered, so there's nothing for them to do.

Do steps 3 and 4 close together: between them, anyone signing in for the first
time gets a gateway key before Cumulate knows where the gateway is.

**5. Retire the old shared key.** Every machine that ran Cumulate before this
holds the old shared OpenAI key. Once everyone has started once, **revoke that
key at OpenAI**, and remove the setting that's no longer used:
`supabase secrets unset FALLBACK_OPENAI_KEY`.

## Day to day

All of this happens in the Supabase SQL Editor.

- **Approve someone:** `insert into allowed_emails (email) values ('person@company.com');`
- **Remove someone:** `delete from allowed_emails where email = 'person@company.com';`
  Their key stops working within 30 seconds.
- **One person's budget:**

      insert into gateway_budgets (email, monthly_usd) values ('person@company.com', 50)
      on conflict (email) do update set monthly_usd = excluded.monthly_usd;

  Everyone else's is `MONTHLY_BUDGET_USD` in `wrangler.toml`. Change it there,
  then `npx wrangler deploy`.
- **Spend this month:**

      select e.email, round(sum(u.cost_usd), 2) as usd,
             sum(u.input_tokens) as input_tokens, sum(u.output_tokens) as output_tokens
      from gateway_usage u join engineers e on e.id = u.engineer
      where u.at >= date_trunc('month', now())
      group by e.email order by usd desc;

- **Change model:** `CUMULATE_MODEL` in cumulate's `config.env`. It needs a price in
  `PRICES` when budgets are on, and `ALLOWED_MODELS` can restrict what people can use.

Budgets reset on the 1st of each month (UTC). A request that starts under budget
is allowed to finish, so someone can go slightly over on their last request.

## If something goes wrong

- **"This key is not valid any more"** in Codex: the person was removed, or was
  issued a newer key elsewhere. Starting Cumulate again gets a new key, if
  they're still approved.
- **"budget ... is used up":** raise it as above. It takes effect within 30 seconds.
- **"cannot check keys right now"** (502): the Worker couldn't reach Supabase.
  Check `SUPABASE_URL` in `wrangler.toml` and the `SUPABASE_SECRET_KEY` secret.
- **Live logs:** `npx wrangler tail` shows each request as it happens (no contents).

## Tests

    deno test worker.test.ts

To run it locally, put the two secrets in a `.dev.vars` file here (it's
gitignored) and run `npx wrangler dev`.
