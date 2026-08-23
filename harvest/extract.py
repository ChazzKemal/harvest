"""Turn one session into knowledge claims, using the OpenAI API."""
from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

CLAIM_TYPES = [
    "data_semantics",      # what a column/field actually means, vs what it's called
    "hygiene_rule",        # which rows are junk, dedupe, null handling
    "implicit_constraint",  # a real constraint nobody ever modelled
    "objective_tradeoff",   # what "good" means; weights, preferences
    "acceptance_heuristic",  # how they know an answer is wrong by looking at it
    "exception_override",   # what gets changed by hand after the fact
    "vocabulary",          # org term -> what it maps to
]

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["headline", "what_was_built", "claims", "corrections", "open_questions"],
    "properties": {
        "headline": {"type": "string", "description": "One line: what this session was about."},
        "what_was_built": {"type": "string", "description": "2-3 sentences, plain language."},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "claim", "evidence", "why", "confidence", "generalises"],
                "properties": {
                    "type": {"type": "string", "enum": CLAIM_TYPES},
                    "claim": {"type": "string", "description": "One sentence, stated as a rule."},
                    "evidence": {"type": "string", "description": "Verbatim quote from the transcript. Never paraphrase."},
                    "why": {"type": "string", "description": "The reason they gave, if any. Empty if they didn't."},
                    "confidence": {"type": "string", "enum": ["stated", "implied", "inferred"]},
                    "generalises": {"type": "boolean", "description": "False if this is a one-off about this file only."},
                },
            },
        },
        "corrections": {
            "type": "array",
            "description": "Where the agent was wrong and the person fixed it. The most valuable part.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["agent_assumed", "person_said", "evidence"],
                "properties": {
                    "agent_assumed": {"type": "string"},
                    "person_said": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
        "open_questions": {
            "type": "array",
            "description": "Things left unresolved that a human should follow up on.",
            "items": {"type": "string"},
        },
    },
}

SYSTEM = """You read one session between an engineer and a coding agent, and pull out what
the engineer knows about their domain that is not written down anywhere else.

The engineer is a domain expert. The session exists to get them a small tool, but the
reason we are reading it is to capture their expertise.

What matters most, in order:

1. CORRECTIONS. Anywhere the agent assumed something and the engineer said no. That is
   tacit knowledge becoming explicit, and it is the single most valuable thing here.
2. REACTIONS TO OUTPUT. Anywhere they looked at a result and said it was wrong, or
   surprising, or "that can't be right". How they judge correctness is knowledge that
   exists nowhere else.
3. REASONS. When they explain WHY a rule exists. The rule alone does not transfer; the
   reason does.
4. Stated rules, constraints, and definitions.

Hard rules:

- Every claim needs a VERBATIM quote from the transcript as evidence. Never paraphrase
  into the evidence field. If you cannot quote it, do not claim it.
- Do not invent. Do not smooth over. If the session contains no domain knowledge, return
  an empty claims list. An honest empty result is far more useful than a padded one.
- One instance is an anecdote, not a rule. If something was said once about one file,
  set generalises=false.
- confidence: "stated" = they said it outright. "implied" = clear from context.
  "inferred" = you worked it out. Prefer stated. Be sparing with inferred.
- Ignore anything about code mechanics, libraries, errors, or tooling. That is noise.
  We only want domain knowledge."""


def client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY not set. Copy .env.example to .env and add your key.")
    return OpenAI(api_key=key)


def model() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-5.6-sol")


def extract(transcript: str, diff: str, commits: str, *, model_name: str | None = None) -> dict:
    body = f"""## Transcript

{transcript[:120_000]}

## Code changes

{diff[:40_000] or "(none)"}

## Commits

{commits[:4_000] or "(none)"}"""

    resp = client().chat.completions.create(
        model=model_name or model(),
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": body}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "session_knowledge", "strict": True, "schema": SCHEMA},
        },
    )
    return json.loads(resp.choices[0].message.content)
