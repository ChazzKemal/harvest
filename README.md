# Harvest

Reads agent sessions after the fact and writes down what the engineer knows.

Points at any repo where Entire is enabled. Pulls the transcript, the diff and the
commits for each session, sends them to the OpenAI API, and writes a page per session
plus a growing file of typed claims.

## Setup

    cp .env.example .env        # paste your OpenAI key   (Windows: copy .env.example .env)
    uv venv --python 3.12 && uv pip install -r requirements.txt

## Two separate things

**Chats are always kept.** Free, no model call, every session. `harvest capture` runs
from a Codex hook on every session start and end. This is not optional and never
depends on committing.

**Summarising is deliberate.** On demand, or weekly:

    python -m harvest capture --repo ../Cumulate     # keep chats (free, automatic)
    python -m harvest run     --repo ../Cumulate     # summarise now
    python -m harvest weekly  --repo ../Cumulate     # summarise the week's committed work
    python -m harvest page                           # rebuild the HTML

## Where sessions come from

Two sources, **merged** — they are complementary, not redundant:

- **Entire checkpoints** — the commit and the diff
- **Codex's own store** (`~/.codex/thread_history_*.sqlite`) — the structured turns:
  prompts, responses, tool calls, reasoning

Entire gets its transcript the same way: its hooks read Codex's own store and render
it back as `[User]` / `[Assistant]` / `[Tool]`. Taking one source and discarding the
other loses half of every session.

## The shared store

Each engineer captures on their own machine and uploads their own rows. Row-level
security does the rest: they read only what they wrote, you read everything.

    psql "$SUPABASE_DB_URL" -f supabase/schema.sql   # once
    python supabase/test_isolation.py                # prove the boundary holds

People sign themselves in — one Google button in the tool window, no account to
create and nothing to paste. A database trigger gives each new sign-in its own
`engineers` row, so there is nothing to provision.

Signing in creates an account; it does not grant a key. `issue-key` is
default-deny: anyone in the world can sign in with a Google account, so the
shared `FALLBACK_OPENAI_KEY` is only handed to emails you have approved:

    insert into allowed_emails (email) values ('person@company.com');

A personal row in `api_keys` also works and takes precedence. Everyone else
gets 403 and spends nothing.

From then on `capture` uploads automatically; `python -m harvest upload`
backfills anything from before sharing was switched on, and every tool has a
**Send everything now** button for the same thing. Uploads are fingerprinted, so re-running never
duplicates, and an unreachable database just means it retries next session.

Run the isolation test before real data goes in. A wrong policy looks exactly
like a right one until someone runs the query that proves otherwise.

## Two views

    ./view.command     # an engineer's own knowledge, read from their local out/
    ./admin.command    # everything, from everyone — yours only

On Windows the same two are `view.cmd` and `admin.cmd` — double-click them.

`admin.command` builds `out/admin.html`: sessions with the full conversation and
the diff beside it, what people got stuck on, what they asked for, and what is
known — filterable by person, tool and project.

Extraction runs in one place, on your key, over everyone's uploaded sessions:

    python -m harvest extract --dry-run   # what it would spend
    python -m harvest extract             # do it

The admin view leads with **where people got stuck**: every correction, grouped by
tool, because the tool with the most corrections is the one whose assumptions are
wrong. Then what people asked for — with requests typed into a tool's box marked
apart from the ones Harvest inferred — and then the claims.

`admin.command` reads the secret key and bypasses every policy. Never hand it out.

## Browsing it

    open out/index.html

One self-contained dark page. Sessions render as the conversation actually happened —
prompts, responses, collapsed tool calls — with filters and counts down the side.
Sessions not yet summarised are marked with a dot; their chat is still there in full.

## Spending

Sessions are gated before any API call, deterministically — no model decides this.

**Anything that produced changes is always recorded**, however few words it took to
ask for it. "refactor it" counts. The gate exists only to avoid paying to be told that
an empty session was empty.

Skipped for free — and only these:

- launcher prompts only, nothing changed — nobody actually said anything
- "yes" / "ok thanks" with nothing changed (under 3 words, `--min-words` to change)

`--force` ignores the gate. `--dry-run` shows the verdict per session without calling
anything.

**Skipped sessions are still recorded.** Every real thing a person asked for is
appended to `out/asks.jsonl` regardless — a working one-shot is still a complete spec,
and that index tells you what people actually want built. It costs nothing.

## Browsing it

    ./view.command        # or: ./.venv/bin/streamlit run harvest/viewer.py

Knowledge is grouped by the tool it came from — each tool a collapsible group — so you
can see what is known about `shipment-cost` without wading through everything else.
Click a tool header to fold it, or use **Expand all tools** in the side rail. What you
fold stays folded across reloads, per browser. Filtering force-opens any group that
still has matches, so a collapsed group never hides your only result.

Three tabs: **Knowledge** (every claim, filterable by type, confidence, and whether it
generalises), **Sessions** (the full report per session), and **What people asked for**
(every request, extracted or not — this is your roadmap signal).

## Output

    out/sessions/2026-08-23-a1b2c3d4e5f6.md   one readable page per session
    out/claims.jsonl                          every claim, appended, machine-readable

Each claim carries a verbatim quote as evidence, a confidence (`stated` / `implied` /
`inferred`), and whether it generalises or is about one file only.

## What it looks for, in order

1. **Corrections** — where the agent assumed something and the engineer said no.
   Tacit knowledge becoming explicit. The most valuable thing in any session.
2. **Reactions to output** — "that can't be right". How they judge correctness.
3. **Reasons** — the why behind a rule. The rule doesn't transfer; the reason does.
4. Stated rules, constraints, definitions.

It ignores code mechanics, errors and tooling entirely. That's noise.

## Claim types

`data_semantics` · `hygiene_rule` · `implicit_constraint` · `objective_tradeoff` ·
`acceptance_heuristic` · `exception_override` · `vocabulary`

## Why the output is committed

`out/` is tracked, deliberately. Codex's store is per-machine and gets pruned;
Entire's uncommitted session state lives in `.git/entire-sessions/` and is wiped by
`entire clean`. Neither is a durable home for knowledge.

Once a session is harvested, the summary and its claims live **here**, in this repo,
version controlled. That is the record. The upstream sources are just feeds.

## Important

**Nothing here is truth.** These are extracted claims with evidence attached, for a
human to read and promote. Never feed `claims.jsonl` straight into anything. The model
will occasionally over-generalise from a single remark — that's what the `generalises`
flag and the quote are for.

An empty result is a real result. Sessions where the agent got it right first time
genuinely contain no new knowledge.
