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

from . import snapshot
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


def _as_diff(rel: str, change: dict) -> str:
    """One edit as a unified diff the admin page can colour.

    Codex keeps a new file whole and an edit to an existing one as its hunks,
    so an added file is written out as all "+" lines.
    """
    kind = (change.get("kind") or {}).get("type")
    lines = (change.get("diff") or "").splitlines()
    if kind == "add":
        head = [f"diff --git a/{rel} b/{rel}", "new file", "--- /dev/null", f"+++ b/{rel}",
                f"@@ -0,0 +1,{len(lines)} @@"]
        return "\n".join(head + ["+" + l for l in lines])
    if kind == "delete":
        head = [f"diff --git a/{rel} b/{rel}", "deleted file", f"--- a/{rel}", "+++ /dev/null",
                f"@@ -1,{len(lines)} +0,0 @@"]
        return "\n".join(head + ["-" + l for l in lines])
    return "\n".join([f"diff --git a/{rel} b/{rel}", f"--- a/{rel}", f"+++ b/{rel}"] + lines)


def _connect(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def _under(path: str, repo: Path) -> bool:
    """Is `path` inside `repo`? Case and slashes do not count on Windows."""
    if not path:
        return False
    p = os.path.normcase(os.path.abspath(path))
    r = os.path.normcase(str(repo))
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def _started_in(since_ms: int) -> dict[str, str]:
    """Where each recent session was started, from its own session file.

    The first line of every session file names the folder it ran in. Without
    this, a session only counted if it happened to run a shell command there:
    one that only talked, or only edited files, went missing.
    """
    out: dict[str, str] = {}
    for f in (CODEX_DIR / "sessions").rglob("rollout-*.jsonl"):
        try:
            if f.stat().st_mtime * 1000 < since_ms:
                continue
            with f.open(encoding="utf-8") as fh:
                meta = json.loads(fh.readline()).get("payload") or {}
        except (OSError, ValueError, AttributeError):
            continue
        if meta.get("id") and meta.get("cwd"):
            out[meta["id"]] = meta["cwd"]
    return out


# The launcher's own opening message. A session with nothing but this - opened
# and closed again - is not worth a place in the record.
LAUNCH_PROMPT = "You are in the Tool Builder project."


def sessions_for(repo: Path, since_days: int = 30) -> list[Session]:
    """Every Codex session that ran inside `repo`: started there, ran a command
    there, or changed a file there."""
    repo = Path(repo).resolve()
    cutoff = int((datetime.now(timezone.utc) - timedelta(days=since_days)).timestamp() * 1000)
    started = _started_in(cutoff)
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
            in_repo = _under(started.get(tid, ""), repo)
            for itype, js, ms in items:
                try:
                    d = json.loads(js)
                except json.JSONDecodeError:
                    continue
                if itype == "commandExecution" and _under(d.get("cwd", ""), repo):
                    in_repo = True
                if itype == "fileChange" and any(
                        _under((c or {}).get("path", ""), repo) for c in d.get("changes") or []):
                    in_repo = True
                parsed.append((itype, d, ms))

            if not in_repo:
                continue

            s = Session(checkpoint_id=f"codex:{tid[:12]}", session_id=tid, agent="Codex")
            first_ms = min(m for _, _, m in parsed)
            s.started_at = datetime.fromtimestamp(first_ms / 1000, timezone.utc).isoformat()

            lines: list[str] = []
            diffs: list[str] = []
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
                        # Forward slashes, on Windows too: everything
                        # downstream matches paths like "tools/<name>/", and a
                        # backslashed path matched none of them.
                        try:
                            rel = Path(raw).relative_to(repo).as_posix()
                        except ValueError:
                            rel = Path(raw).as_posix()
                        paths.append(rel)
                        if rel not in s.files:
                            s.files.append(rel)
                        if snapshot.shareable(rel):
                            diffs.append(_as_diff(rel, ch))
                    s.turns.append({"role": "tool", "kind": "edit",
                                    "text": ", ".join(paths), "ts": ts})

            # Opened, greeted, closed: nothing was asked and nothing was made.
            if not s.files and all(p.startswith(LAUNCH_PROMPT) for p in s.prompts):
                continue

            # What changed, from Codex's own record of every edit. Entire gives
            # a diff only once the workspace has commits, and most never do.
            if diffs and not s.diff:
                s.diff = "\n".join(diffs)
            s.transcript = "\n\n".join(lines)
            # This builder is the one that knows which files were touched, so
            # it is the one that can say what the code looked like afterwards.
            snapshot.enrich(repo, s)
            out.append(s)

    out.sort(key=lambda x: x.started_at, reverse=True)
    return out
