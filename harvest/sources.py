"""Pull the raw material for one session: what was said, what changed, what was committed."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from pathlib import Path


def _run(args: list[str], cwd: Path | None = None) -> str:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])} failed: {r.stderr.strip()[:300]}")
    return r.stdout


@dataclass
class Session:
    checkpoint_id: str
    session_id: str = ""
    agent: str = ""
    model: str = ""
    started_at: str = ""
    prompts: list[str] = field(default_factory=list)
    transcript: str = ""
    diff: str = ""
    commits: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    turns: list[dict] = field(default_factory=list)
    tokens: dict = field(default_factory=dict)
    author: str = ""
    checkpoint_count: int = 0
    added: int = 0
    removed: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.transcript.strip() or self.prompts)


def checkpoints(repo: Path, since: str = "30d") -> list[dict]:
    """Checkpoints on the current branch. These are the durable record.

    `checkpoint list` has no --since flag, and passing one exits 0 printing usage
    text rather than failing — so filter by date here instead.
    """
    try:
        raw = _run(["entire", "checkpoint", "list", "--json"], cwd=repo)
    except RuntimeError:
        return []

    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []

    cps = data if isinstance(data, list) else data.get("checkpoints", [])

    days = int("".join(c for c in since if c.isdigit()) or 30)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return [c for c in cps if not c.get("date") or c["date"] >= cutoff[:10]]


def _parse_transcript(text: str) -> list[str]:
    """Entire renders turns as [User] / [Assistant] / [Tool] blocks."""
    return [m.strip() for m in re.findall(
        r"^\[User\]\s*(.+?)(?=^\[(?:User|Assistant|Tool)\]|\Z)",
        text, re.MULTILINE | re.DOTALL)]


def sessions(repo: Path, since: str = "30d") -> list[Session]:
    """Checkpoints grouped into one Session each — a session can have several."""
    by_session: dict[str, list[dict]] = {}
    for cp in checkpoints(repo, since):
        by_session.setdefault(cp.get("session_id") or cp.get("checkpoint_id", ""), []).append(cp)

    out: list[Session] = []
    for sid, cps in by_session.items():
        cps.sort(key=lambda c: c.get("date", ""))
        s = Session(checkpoint_id=cps[-1].get("checkpoint_id", ""), session_id=sid, agent="Codex")
        s.started_at = cps[0].get("date", "")

        parts: list[str] = []
        for cp in cps:
            cid = cp.get("checkpoint_id", "")
            # The commit message on a checkpoint is the prompt that produced it.
            if msg := (cp.get("message") or "").strip():
                s.prompts.append(msg)
            try:
                parts.append(_run(["entire", "checkpoint", "explain", cid], cwd=repo))
            except RuntimeError:
                pass

        s.transcript = "\n\n".join(parts)
        # Prefer real user turns from the transcript when we can read them.
        if turns := _parse_transcript(s.transcript):
            s.prompts = turns + [p for p in s.prompts if p not in turns]

        # `checkpoint list --json` carries no commit field. `explain` does, either
        # as a "commits  <sha> <subject>" header or as "(<sha>)" in a list line.
        s.commits = [c.get("commit", "") for c in cps if c.get("commit")]
        if not s.commits:
            found = re.findall(r"^\s*commits?\s+([0-9a-f]{7,40})\b", s.transcript, re.MULTILINE)
            found += [m.strip("()") for m in
                      re.findall(r"\([0-9a-f]{7,40}\)", s.transcript)]
            for sha in found:
                if sha in s.commits:
                    continue
                try:
                    _run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo)
                    s.commits.append(sha)
                except RuntimeError:
                    continue

        s.files = sorted(set(s.files) | {f for c in cps for f in (c.get("files") or [])})
        s.checkpoint_count = len(cps)
        if m := re.search(r"^\s*author\s+(.+?)\s*<", s.transcript, re.MULTILINE):
            s.author = m.group(1).strip()
        s.tokens = token_usage(repo, sid)
        s.added, s.removed = diff_stats(repo, s)
        s.diff = session_diff(repo, s)
        out.append(s)

    out.sort(key=lambda x: x.started_at, reverse=True)
    return out


def token_usage(repo: Path, session_id: str) -> dict:
    """Token counts for a session, straight from Entire."""
    if not session_id:
        return {}
    try:
        d = json.loads(_run(["entire", "session", "tokens", session_id, "--json"], cwd=repo))
    except (RuntimeError, json.JSONDecodeError):
        return {}
    return d.get("tokens", {}) if isinstance(d, dict) else {}


def session_diff(repo: Path, sess) -> str:
    """The actual patch a session produced.

    added/removed were being counted while the patch itself was thrown away, so
    the record could say sixty lines changed without being able to show which.
    The commits are already linked to the session, so the exact change is one
    `git show` away — no guessing from timestamps.
    """
    parts = []
    for sha in sess.commits:
        try:
            parts.append(_run(["git", "show", "--patch", "--format=commit %H%n%s%n", sha],
                              cwd=repo))
        except RuntimeError:
            continue
    if parts:
        return "\n".join(parts)[:200_000]

    # Nothing committed yet: whatever is still uncommitted is the best available
    # picture of what this session did.
    try:
        return working_diff(repo)
    except RuntimeError:
        return ""


def diff_stats(repo: Path, sess) -> tuple[int, int]:
    """Lines added and removed, committed or not."""
    added = removed = 0
    try:
        if sess.commits:
            raw = _run(["git", "show", "--numstat", "--format=", sess.commits[-1]], cwd=repo)
        else:
            raw = _run(["git", "diff", "--numstat", "HEAD"], cwd=repo)
            for f in _run(["git", "ls-files", "--others", "--exclude-standard"],
                          cwd=repo).splitlines():
                fp = repo / f.strip()
                if f.strip() and fp.is_file():
                    try:
                        added += len(fp.read_text(errors="replace").splitlines())
                    except OSError:
                        pass
    except RuntimeError:
        return added, removed

    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            a, r = parts[0], parts[1]
            added += int(a) if a.isdigit() else 0
            removed += int(r) if r.isdigit() else 0
    return added, removed


def active_sessions(repo: Path, quiet_minutes: int = 3) -> set[str]:
    """Sessions that may still be running. Reading one mid-flight gets half a story.

    Entire reports every session as `idle`, including ones whose window is long
    closed, so status is no help. Fall back to staleness: a session untouched for
    `quiet_minutes` is safe to read. The session that just ended is passed in
    explicitly by the hook instead of being guessed at here.
    """
    try:
        data = json.loads(_run(["entire", "session", "list", "--json"], cwd=repo) or "[]")
    except (RuntimeError, json.JSONDecodeError):
        return set()

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=quiet_minutes)
    live: set[str] = set()
    for s in data:
        if not isinstance(s, dict) or not s.get("session_id"):
            continue
        try:
            if datetime.fromisoformat(s.get("last_active", "")) > cutoff:
                live.add(s["session_id"])
        except (TypeError, ValueError):
            continue
    return live


def git_log(repo: Path, since: str = "30 days ago") -> str:
    return _run(["git", "log", f"--since={since}", "--format=%h %ad %s", "--date=short"], cwd=repo)


def working_diff(repo: Path) -> str:
    """Uncommitted changes — the fallback when a session never committed."""
    return _run(["git", "diff", "HEAD"], cwd=repo)[:60_000]
