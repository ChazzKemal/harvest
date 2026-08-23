"""Every conversation, kept. No model involved, no cost, no judgement.

Summarising is a separate, deliberate act. This just makes sure the raw material
is never lost — Codex prunes its store, and Entire's uncommitted state is local
and wiped by `entire clean`.
"""
from __future__ import annotations

import json
from pathlib import Path


def dir_for(out: Path) -> Path:
    d = out / "chats"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(out: Path, sess) -> tuple[Path, bool]:
    """Write a session's chat. Returns (path, changed)."""
    f = dir_for(out) / f"{(sess.session_id or sess.checkpoint_id).replace(':', '-')}.json"
    payload = {
        "session_id": sess.session_id,
        "checkpoint_id": sess.checkpoint_id,
        "agent": sess.agent,
        "model": sess.model,
        "started_at": sess.started_at,
        "files": sess.files,
        "commits": sess.commits,
        "prompts": sess.prompts,
        "turns": sess.turns,
        "transcript": sess.transcript,
    }
    new = json.dumps(payload, indent=1, ensure_ascii=False)
    if f.exists() and f.read_text(encoding="utf-8") == new:
        return f, False
    f.write_text(new, encoding="utf-8")
    return f, True


def load_all(out: Path) -> list[dict]:
    d = out / "chats"
    if not d.exists():
        return []
    chats = []
    for f in sorted(d.glob("*.json")):
        try:
            chats.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    chats.sort(key=lambda c: c.get("started_at", ""), reverse=True)
    return chats


def counts(chat: dict) -> dict:
    turns = chat.get("turns", [])
    return {
        "prompts": sum(1 for t in turns if t["role"] == "user"),
        "responses": sum(1 for t in turns if t["role"] == "assistant"),
        "tools": sum(1 for t in turns if t["role"] == "tool"),
        "reasoning": sum(1 for t in turns if t["role"] == "reasoning"),
    }
