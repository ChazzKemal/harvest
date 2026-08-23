"""Read sessions straight out of Codex's own store.

Entire only records a session that committed. Codex keeps every session regardless,
in ~/.codex/thread_history_*.sqlite. Reading it here means a conversation is never
lost just because the agent didn't commit — and nothing has to be copied into the
repo to achieve that.

Read-only. We never write to Codex's database.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .sources import Session

CODEX_DIR = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


def _dbs() -> list[Path]:
    return sorted(CODEX_DIR.glob("thread_history_*.sqlite"))


def _text(item: dict) -> str:
    """Pull display text out of an item, whatever shape it uses."""
    if isinstance(item.get("text"), str):
        return item["text"]
    content = item.get("content")
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    if isinstance(content, str):
        return content
    return ""


def _connect(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def sessions_for(repo: Path, since_days: int = 30) -> list[Session]:
    """Every Codex session whose commands ran inside `repo`."""
    repo = str(Path(repo).resolve())
    cutoff = int((datetime.now(timezone.utc) - timedelta(days=since_days)).timestamp() * 1000)
    out: list[Session] = []

    for db in _dbs():
        try:
            con = _connect(db)
            rows = con.execute(
                """select thread_id, item_type, item_json, created_at_ms
                   from thread_items where created_at_ms >= ?
                   order by thread_id, rollout_ordinal""", (cutoff,)).fetchall()
        except sqlite3.Error:
            continue

        threads: dict[str, list] = {}
        for tid, itype, js, ms in rows:
            threads.setdefault(tid, []).append((itype, js, ms))

        for tid, items in threads.items():
            parsed = []
            in_repo = False
            for itype, js, ms in items:
                try:
                    d = json.loads(js)
                except json.JSONDecodeError:
                    continue
                if itype == "commandExecution" and d.get("cwd", "").startswith(repo):
                    in_repo = True
                parsed.append((itype, d, ms))

            if not in_repo:
                continue

            s = Session(checkpoint_id=f"codex:{tid[:12]}", session_id=tid, agent="Codex")
            first_ms = min(m for _, _, m in parsed)
            s.started_at = datetime.fromtimestamp(first_ms / 1000, timezone.utc).isoformat()

            lines: list[str] = []
            for itype, d, _ in parsed:
                if itype == "userMessage":
                    t = _text(d).strip()
                    if t:
                        s.prompts.append(t)
                        lines.append(f"USER: {t}")
                elif itype == "agentMessage":
                    t = _text(d).strip()
                    if t:
                        lines.append(f"AGENT: {t}")
                elif itype == "commandExecution":
                    cmd = (d.get("command") or "").strip()
                    if cmd:
                        lines.append(f"[ran] {cmd[:200]}")
                elif itype == "fileChange":
                    for p in d.get("paths", []) or ([d["path"]] if d.get("path") else []):
                        if p not in s.files:
                            s.files.append(p)

            s.transcript = "\n\n".join(lines)
            out.append(s)

    out.sort(key=lambda x: x.started_at, reverse=True)
    return out
