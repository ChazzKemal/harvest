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
    repo = Path(repo).resolve()
    repo_s = str(repo)
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
                if itype == "commandExecution" and d.get("cwd", "").startswith(repo_s):
                    in_repo = True
                parsed.append((itype, d, ms))

            if not in_repo:
                continue

            s = Session(checkpoint_id=f"codex:{tid[:12]}", session_id=tid, agent="Codex")
            first_ms = min(m for _, _, m in parsed)
            s.started_at = datetime.fromtimestamp(first_ms / 1000, timezone.utc).isoformat()

            lines: list[str] = []
            for itype, d, ms in parsed:
                ts = datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()
                if itype == "userMessage":
                    txt = _text(d).strip()
                    if txt:
                        s.prompts.append(txt)
                        lines.append(f"USER: {txt}")
                        s.turns.append({"role": "user", "text": txt, "ts": ts})
                elif itype == "agentMessage":
                    txt = _text(d).strip()
                    if txt:
                        lines.append(f"AGENT: {txt}")
                        s.turns.append({"role": "assistant", "text": txt, "ts": ts})
                elif itype == "commandExecution":
                    cmd = (d.get("command") or "").strip()
                    if cmd:
                        lines.append(f"[ran] {cmd[:200]}")
                        s.turns.append({"role": "tool", "kind": "exec", "text": cmd,
                                        "output": (d.get("aggregatedOutput") or "")[:2000],
                                        "status": d.get("status", ""), "ts": ts})
                elif itype == "reasoning":
                    s.turns.append({"role": "reasoning", "text": _text(d).strip()[:2000], "ts": ts})
                elif itype == "fileChange":
                    # Shape is changes:[{path, kind, diff}] with absolute paths.
                    paths = []
                    for ch in d.get("changes", []) or []:
                        raw = ch.get("path") if isinstance(ch, dict) else None
                        if not raw:
                            continue
                        try:
                            rel = str(Path(raw).relative_to(repo))
                        except ValueError:
                            rel = raw
                        paths.append(rel)
                        if rel not in s.files:
                            s.files.append(rel)
                    s.turns.append({"role": "tool", "kind": "edit",
                                    "text": ", ".join(paths), "ts": ts})

            s.transcript = "\n\n".join(lines)
            out.append(s)

    out.sort(key=lambda x: x.started_at, reverse=True)
    return out
