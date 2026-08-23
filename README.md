# Harvest

Reads agent sessions after the fact and writes down what the engineer knows.

Points at any repo where Entire is enabled. Pulls the transcript, the diff and the
commits for each session, sends them to the OpenAI API, and writes a page per session
plus a growing file of typed claims.

## Setup

    cp .env.example .env        # paste your OpenAI key
    uv venv --python 3.12 && uv pip install -r requirements.txt

## Where sessions come from

Two sources, both read by default:

- **Entire checkpoints** — richer: transcript plus the diff and the commit it produced.
  Only exists if the session committed.
- **Codex's own store** (`~/.codex/thread_history_*.sqlite`) — every session, committed
  or not, filtered to the ones whose commands ran inside the target repo.

So a conversation is never lost just because the agent didn't commit, and nothing has
to be copied into your repo to achieve that. Codex's database is opened **read-only**.

When both sources have the same session, the Entire one wins — it has the diff.

    --source both     # default
    --source entire   # checkpoints only
    --source codex    # Codex store only

## Use

    python -m harvest run --repo ../Cumulate          # new sessions since last run
    python -m harvest run --repo ../Cumulate --since 7d
    python -m harvest run --repo ../Cumulate --dry-run  # show what would be sent
    python -m harvest run --repo ../Cumulate --working  # uncommitted work, no checkpoint
    python -m harvest models                           # what your key can use

Already-processed checkpoints are skipped. `--force` reprocesses them.

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
