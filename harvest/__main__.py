"""harvest — read agent sessions, write down what the engineer knows.

    python -m harvest run --repo ../Cumulate
    python -m harvest run --repo ../Cumulate --working   # no checkpoint yet
    python -m harvest models                             # what can my key use?
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import codex_store, sources
from .extract import extract
from .gate import assess, human_turns
from .render import to_markdown

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"


def _load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _state(sess) -> str:
    """A session reported from a commit beats one reported mid-flight."""
    return "committed" if sess.commits else "temp"


def _seen() -> dict[str, str]:
    """session_id -> best state already reported.

    Keyed by session, not checkpoint: checkpoint IDs change when temporary
    checkpoints are consolidated on commit, so keying on them would re-report
    the same conversation under a new id.
    """
    f = OUT / ".processed"
    if not f.exists():
        return {}
    out: dict[str, str] = {}
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                d = json.loads(line)
                out[d["session"]] = d.get("state", "temp")
            except (json.JSONDecodeError, KeyError):
                continue
        else:
            out[line] = "temp"   # legacy entries
    return out


def _mark(sess) -> None:
    OUT.mkdir(exist_ok=True)
    key = sess.session_id or sess.checkpoint_id
    with (OUT / ".processed").open("a") as f:
        f.write(json.dumps({"session": key, "state": _state(sess),
                            "checkpoint": sess.checkpoint_id}) + "\n")


def _already_done(sess, seen: dict[str, str]) -> bool:
    key = sess.session_id or sess.checkpoint_id
    prev = seen.get(key)
    if prev is None:
        return False
    # Re-report once a session gains a commit — the diff makes a better report.
    return not (prev == "temp" and _state(sess) == "committed")


def _log_asks(sess, decision) -> None:
    """Every real thing a person asked for, recorded for nothing.

    A one-shot that works is still a complete spec — worth keeping even when there
    is no back-and-forth to extract. Costs no API call.
    """
    turns = human_turns(sess)
    if not turns:
        return
    OUT.mkdir(exist_ok=True)
    with (OUT / "asks.jsonl").open("a") as f:
        f.write(json.dumps({
            "checkpoint": sess.checkpoint_id,
            "session": sess.session_id,
            "date": (sess.started_at or datetime.now(timezone.utc).isoformat())[:10],
            "asks": turns,
            "files": sess.files,
            "extracted": decision.run,
            "words": decision.human_words,
        }) + "\n")


def _slug(sess) -> str:
    """A filename that is unique per session and legal on every platform."""
    raw = sess.session_id or sess.checkpoint_id
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in raw)
    return safe.strip("-")[:24] or "session"


def _write(sess, result: dict, label: str) -> Path:
    (OUT / "sessions").mkdir(parents=True, exist_ok=True)
    stamp = (sess.started_at or datetime.now(timezone.utc).isoformat())[:10]
    path = OUT / "sessions" / f"{stamp}-{label}.md"
    path.write_text(to_markdown(sess, result))

    # A session can be reported more than once (a temporary checkpoint later gains
    # a commit). Drop its previous claims before appending, or they accumulate.
    key = sess.session_id or label
    cf = OUT / "claims.jsonl"
    kept = [l for l in cf.read_text().splitlines() if l.strip()
            and json.loads(l).get("session") != key] if cf.exists() else []
    with cf.open("w") as f:
        for line in kept:
            f.write(line + "\n")
        for c in result.get("claims", []):
            f.write(json.dumps({**c, "session": key,
                                "checkpoint": sess.checkpoint_id,
                                "agent": sess.agent, "date": stamp}) + "\n")
    return path


def cmd_run(args) -> int:
    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        print(f"Not a git repo: {repo}", file=sys.stderr)
        return 1

    if args.working:
        diff = sources.working_diff(repo)
        if not diff.strip():
            print("No uncommitted changes to summarise.")
            return 0
        sess = sources.Session(checkpoint_id="working", agent="(uncommitted)")
        sess.diff, sess.transcript = diff, "(no transcript — uncommitted working tree)"
        d = assess(sess, min_words=args.min_words)
        if not d.run and not args.force:
            print(f"Skipped without spending: {d}")
            return 0
        if args.dry_run:
            print(f"Would send {len(diff)} chars of diff, no transcript.")
            return 0
        result = extract(sess.transcript, sess.diff, sources.git_log(repo), model_name=args.model)
        print(f"Wrote {_write(sess, result, 'working')}")
        return 0

    candidates: list = []
    seen_sessions: set[str] = set()

    if args.source in ("entire", "both"):
        for s in sources.sessions(repo, args.since):
            candidates.append(s)
            if s.session_id:
                seen_sessions.add(s.session_id)

    if args.source in ("codex", "both"):
        days = int("".join(c for c in args.since if c.isdigit()) or 30)
        for s in codex_store.sessions_for(repo, days):
            # An Entire checkpoint for the same session is richer — it has the diff.
            if s.session_id in seen_sessions:
                continue
            candidates.append(s)

    live = sources.active_sessions(repo) - {args.ended} if args.ended else sources.active_sessions(repo)
    if live:
        before = len(candidates)
        candidates = [c for c in candidates if c.session_id not in live]
        if before - len(candidates):
            print(f"  ({before - len(candidates)} session still running — left alone)")

    if not candidates:
        print("No sessions found.\n"
              "Entire records a session only once it commits; Codex keeps the rest in its\n"
              "own store. Neither had anything for this repo.")
        return 0

    seen, done, skipped = _seen(), 0, 0
    for sess in candidates:
        cid = sess.checkpoint_id
        if _already_done(sess, seen) and not args.force:
            continue
        if sess.is_empty:
            print(f"  {cid[:12]} — empty, skipped")
            skipped += 1
            continue

        d = assess(sess, min_words=args.min_words)
        _log_asks(sess, d)
        if not d.run and not args.force:
            # Deliberately NOT marked as processed. The gate costs nothing to
            # re-run, and a session judged empty may simply still be in progress.
            print(f"  {cid[:12]} — skipped: {d}")
            skipped += 1
            continue

        if args.dry_run:
            print(f"  {cid[:12]} — would send: {d}, "
                  f"{len(sess.transcript)} chars transcript, {len(sess.diff)} chars diff")
            done += 1
            continue
        result = extract(sess.transcript, sess.diff, sources.git_log(repo), model_name=args.model)
        print(f"  {cid[:18]} — {len(result.get('claims', []))} claims, "
              f"{len(result.get('corrections', []))} corrections -> {_write(sess, result, _slug(sess)).name}")
        _mark(sess)
        done += 1

    if done and args.dry_run:
        print(f"\n{done} session(s) would be sent, {skipped} skipped without spending.")
    elif done:
        print(f"\n{done} session(s) processed, {skipped} skipped without spending. "
              f"Claims appended to out/claims.jsonl")
    else:
        print(f"\nNothing worth extracting. {skipped} session(s) skipped, no API calls made.\n"
              f"What people asked for is still recorded in out/asks.jsonl.")
    return 0


def cmd_models(_args) -> int:
    from .extract import client
    names = sorted(m.id for m in client().models.list())
    for n in names:
        print(" ", n)
    print(f"\n{len(names)} models. Set OPENAI_MODEL in .env to pick one.")
    return 0


def main() -> int:
    _load_env()
    p = argparse.ArgumentParser(prog="harvest", description=__doc__,
                               formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="extract knowledge from sessions in a repo")
    r.add_argument("--repo", required=True, help="path to the repo Entire is enabled in")
    r.add_argument("--since", default="30d", help="time window (default 30d)")
    r.add_argument("--model", default=None, help="override OPENAI_MODEL")
    r.add_argument("--source", choices=["entire", "codex", "both"], default="both",
                   help="where to read sessions from (default both)")
    r.add_argument("--working", action="store_true", help="summarise uncommitted changes instead")
    r.add_argument("--ended", default=None,
                   help="session id the hook says just finished — safe to read now")
    r.add_argument("--force", action="store_true",
                   help="reprocess already-seen checkpoints and ignore the spend gate")
    r.add_argument("--min-words", type=int, default=3,
                   help="skip sessions where nothing changed and fewer words were typed (default 3)")
    r.add_argument("--dry-run", action="store_true", help="show what would be sent, call nothing")
    r.set_defaults(fn=cmd_run)

    m = sub.add_parser("models", help="list models your key can use")
    m.set_defaults(fn=cmd_models)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
