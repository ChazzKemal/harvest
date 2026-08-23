"""Decide whether a session is worth spending an API call on.

Entirely deterministic — no model involved. The point is to never pay to be told
that nothing happened.

The signal is how much the *human* typed. A large diff with no conversation is the
agent doing mechanical work and carries no domain knowledge. A one-line diff after a
long back-and-forth is exactly what we want. So we count human words, not changes.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# Prompts the launcher injects. Not the engineer talking — never count them.
BOILERPLATE = (
    "you are in the tool builder project",
    "follow agents.md",
    "check the inbox folder",
    "files waiting in the inbox",
    "files in the inbox",
    "the inbox is empty",
    "greet me in one line",
    "profile the most likely one",
    "these are gitignored",
    "the inbox is gitignored",
)

# Deliberately low. This only filters "yes" / "ok thanks" — anything that reads like
# a real instruction gets recorded. Work that produced changes is always recorded,
# however few words it took to ask for it.
MIN_HUMAN_WORDS = 3


@dataclass
class Decision:
    run: bool
    reason: str
    human_words: int = 0
    human_turns: int = 0

    def __str__(self) -> str:
        return f"{self.reason} ({self.human_turns} turns, {self.human_words} words)"


def _is_boilerplate(text: str) -> bool:
    low = " ".join(text.lower().split())
    return any(b in low for b in BOILERPLATE)


def human_turns(sess) -> list[str]:
    """What the engineer actually typed, launcher prompts removed."""
    turns = [p for p in (sess.prompts or []) if p and p.strip()]

    if not turns and sess.transcript:
        # Fall back to parsing the transcript for user turns.
        turns = re.findall(
            r"^\s*(?:USER|User|>|Human)\s*:?\s*(.+?)(?=^\s*(?:AGENT|Assistant|USER|User|Human)\s*:|\Z)",
            sess.transcript, re.MULTILINE | re.DOTALL,
        )

    return [t.strip() for t in turns if t.strip() and not _is_boilerplate(t)]


def fingerprint(sess) -> str:
    return hashlib.sha256(
        ("\n".join(human_turns(sess)) + (sess.diff or "")).encode()
    ).hexdigest()[:16]


def assess(sess, *, min_words: int = MIN_HUMAN_WORDS) -> Decision:
    """Skip only genuinely empty sessions. When in doubt, record it."""
    turns = human_turns(sess)
    words = sum(len(t.split()) for t in turns)
    changed = bool((sess.diff or "").strip()) or bool(sess.files)

    # Something was actually built or changed — always worth recording, however
    # briefly it was asked for. "refactor it" counts.
    if changed and turns:
        return Decision(True, "work was done", words, len(turns))

    if not turns:
        return Decision(False, "nobody typed anything", words, 0)

    if not changed and words < min_words:
        return Decision(False, "nothing said, nothing changed", words, len(turns))

    return Decision(True, "worth reading", words, len(turns))
