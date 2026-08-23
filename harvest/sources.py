"""Pull the raw material for one session: what was said, what changed, what was committed."""
from __future__ import annotations

import json
import subprocess
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

    @property
    def is_empty(self) -> bool:
        return not (self.transcript.strip() or self.prompts)


def checkpoints(repo: Path, since: str = "30d") -> list[dict]:
    """Checkpoints on the current branch. These are the durable record."""
    try:
        raw = _run(["entire", "checkpoint", "list", "--json", "--since", since], cwd=repo)
    except RuntimeError:
        raw = _run(["entire", "checkpoint", "list", "--json"], cwd=repo)
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else data.get("checkpoints", [])


def load(repo: Path, checkpoint_id: str) -> Session:
    s = Session(checkpoint_id=checkpoint_id)

    try:
        s.transcript = _run(["entire", "checkpoint", "explain", checkpoint_id], cwd=repo)
    except RuntimeError as e:
        s.transcript = f"(transcript unavailable: {e})"

    try:
        meta = json.loads(_run(["entire", "checkpoint", "show", checkpoint_id, "--json"], cwd=repo))
        s.session_id = meta.get("session_id", "")
        s.agent = meta.get("agent", "")
        s.model = meta.get("model", "")
        s.started_at = meta.get("started_at", "") or meta.get("created_at", "")
        s.files = meta.get("files", []) or meta.get("modified_files", [])
        for key in ("prompts", "user_prompts"):
            if isinstance(meta.get(key), list):
                s.prompts = [p if isinstance(p, str) else p.get("text", "") for p in meta[key]]
                break
        if commit := meta.get("commit") or meta.get("commit_sha"):
            s.commits = [commit]
    except RuntimeError:
        pass

    if s.commits:
        try:
            s.diff = _run(["git", "show", "--stat", "--patch", s.commits[0]], cwd=repo)[:60_000]
        except RuntimeError:
            pass

    return s


def git_log(repo: Path, since: str = "30 days ago") -> str:
    return _run(["git", "log", f"--since={since}", "--format=%h %ad %s", "--date=short"], cwd=repo)


def working_diff(repo: Path) -> str:
    """Uncommitted changes — the fallback when a session never committed."""
    return _run(["git", "diff", "HEAD"], cwd=repo)[:60_000]
