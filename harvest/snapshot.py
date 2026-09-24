"""The code a session produced, and what it ran against.

A diff says what changed; it does not give you something you can open and edit.
The unirepo needs the file itself, so this keeps the source of every tool the
session touched, at the state it was left in.

Data files are deliberately NOT kept. What is kept is their shape — sheet names,
columns, row counts, a hash — which is enough to read a tool and know what it
operates on, without a byte of anyone's spreadsheet leaving their machine.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

# Big enough for any hand-sized tool; small enough that one runaway file cannot
# fill the store. Truncation is recorded rather than silent.
MAX_FILE = 200_000

# Anything under here is somebody's data, and never leaves their machine.
NEVER = ("inbox/", "projects/", ".env")

TOOL = re.compile(r"^tools/([^/]+)/")


def _text(p: Path) -> tuple[str, bool]:
    """File contents, and whether it had to be cut short."""
    try:
        body = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", False
    if len(body) > MAX_FILE:
        return body[:MAX_FILE], True
    return body, False


def _safe(rel: str) -> bool:
    return not any(rel == n or rel.startswith(n) for n in NEVER)


def tool_slugs(files: list[str]) -> list[str]:
    """Which tools this session touched, from the paths it changed."""
    return sorted({m.group(1) for f in files or [] if (m := TOOL.match(f))})


def sources(repo: Path, files: list[str]) -> dict[str, dict]:
    """Every file of every tool the session touched, as it stands now.

    The whole folder rather than only the changed file: a tool is its code AND
    the assumptions beside it, and half of one is not something you can pick up
    and work on later.
    """
    out: dict[str, dict] = {}
    for slug in tool_slugs(files):
        folder = repo / "tools" / slug
        if not folder.is_dir():
            continue
        for p in sorted(folder.rglob("*")):
            if not p.is_file() or p.suffix in (".pyc", ".png", ".jpg", ".xlsx"):
                continue
            rel = p.relative_to(repo).as_posix()
            if not _safe(rel):
                continue
            body, cut = _text(p)
            out[rel] = {"text": body, "truncated": cut, "bytes": p.stat().st_size}

    # The domain record for the workspace as a whole. Small, and the single most
    # useful thing to read beside somebody else's tool.
    top = repo / "ASSUMPTIONS.md"
    if out and top.is_file():
        body, cut = _text(top)
        out["ASSUMPTIONS.md"] = {"text": body, "truncated": cut,
                                 "bytes": top.stat().st_size}
    return out


def _digest(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def inputs(repo: Path, timeout: float = 20.0) -> list[dict]:
    """What sat in the inbox, described but never copied.

    Profiling runs the workspace's OWN profiler through its own interpreter —
    the same one the tool used. Describing the file a second time here would be
    a second opinion that could disagree with the first, and Harvest has neither
    the dependencies nor any business owning that logic.
    """
    inbox = repo / "inbox"
    if not inbox.is_dir():
        return []

    out = []
    for p in sorted(inbox.iterdir()):
        if not p.is_file() or p.name.startswith("."):
            continue
        meta = {"name": p.name, "bytes": p.stat().st_size, "sha256": _digest(p)}
        meta.update(_profile(repo, p, timeout))
        out.append(meta)
    return out


def _clean(v):
    """Strip NaN and infinity.

    Python writes them as bare NaN/Infinity, which are not valid JSON — a
    profile of a sheet with one blank cell was enough to have the whole upload
    rejected, and the failure surfaced three layers away from the cause.
    """
    if isinstance(v, float):
        return None if v != v or v in (float("inf"), float("-inf")) else v
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def _profile(repo: Path, path: Path, timeout: float) -> dict:
    """Shape only. Silence on failure — metadata is a bonus, never a blocker."""
    py = repo / ".venv" / "bin" / "python"
    if not py.exists():
        py = repo / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        return {}

    code = (
        "import json,sys;sys.path.insert(0,'scaffold');"
        "from ingest import profile;"
        "print(json.dumps(profile(sys.argv[1]), default=str))"
    )
    try:
        r = subprocess.run([str(py), "-c", code, str(path)], cwd=repo,
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return {}
        return {"shape": _clean(json.loads(r.stdout))}
    except Exception:
        return {}


def enrich(repo: Path, sess) -> None:
    """Attach the code and the input shapes to a session, in place.

    Both builders call this. A session arrives from two places — Entire's
    checkpoints and Codex's own store — and only the second knows which files
    were touched. Computing this in one of them left `sources` empty on every
    session that came through the other, which is to say on all of them.
    """
    sess.sources = sources(repo, sess.files)
    sess.inputs = inputs(repo)
