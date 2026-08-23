# Harvest

Reads agent sessions after the fact and writes down what the engineer knows.

Points at any repo where Entire is enabled. Pulls the transcript, the diff and the
commits for each session, sends them to the OpenAI API, and writes a page per session
plus a growing file of typed claims.

## Setup

    cp .env.example .env        # paste your OpenAI key
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

Knowledge is grouped by the tool it came from — each tool a collapsible group —
so you can see what is known about `shipment-cost` without wading through everything
else. Filters still apply across all of them.

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
