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

from . import sources
from .extract import extract
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


def _seen() -> set[str]:
    f = OUT / ".processed"
    return set(f.read_text().split()) if f.exists() else set()


def _mark(cid: str) -> None:
    OUT.mkdir(exist_ok=True)
    with (OUT / ".processed").open("a") as f:
        f.write(cid + "\n")


def _write(sess, result: dict, label: str) -> Path:
    (OUT / "sessions").mkdir(parents=True, exist_ok=True)
    stamp = (sess.started_at or datetime.now(timezone.utc).isoformat())[:10]
    path = OUT / "sessions" / f"{stamp}-{label}.md"
    path.write_text(to_markdown(sess, result))

    with (OUT / "claims.jsonl").open("a") as f:
        for c in result.get("claims", []):
            f.write(json.dumps({**c, "session": sess.session_id or label,
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
        if args.dry_run:
            print(f"Would send {len(diff)} chars of diff, no transcript.")
            return 0
        result = extract(sess.transcript, sess.diff, sources.git_log(repo), model_name=args.model)
        print(f"Wrote {_write(sess, result, 'working')}")
        return 0

    cps = sources.checkpoints(repo, args.since)
    if not cps:
        print("No checkpoints found.\n"
              "Entire only records a session once it saves changes — a conversation that\n"
              "edits nothing leaves no trace. Use --working to summarise uncommitted work.")
        return 0

    seen, done = _seen(), 0
    for cp in cps:
        cid = cp.get("id") or cp.get("checkpoint_id") or ""
        if not cid or (cid in seen and not args.force):
            continue
        sess = sources.load(repo, cid)
        if sess.is_empty:
            print(f"  {cid[:12]} — empty, skipped")
            continue
        if args.dry_run:
            print(f"  {cid[:12]} — would send {len(sess.transcript)} chars transcript, "
                  f"{len(sess.diff)} chars diff")
            continue
        result = extract(sess.transcript, sess.diff, sources.git_log(repo), model_name=args.model)
        print(f"  {cid[:12]} — {len(result.get('claims', []))} claims, "
              f"{len(result.get('corrections', []))} corrections -> {_write(sess, result, cid[:12]).name}")
        _mark(cid)
        done += 1

    print(f"\n{done} session(s) processed. Claims appended to out/claims.jsonl")
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
    r.add_argument("--working", action="store_true", help="summarise uncommitted changes instead")
    r.add_argument("--force", action="store_true", help="reprocess already-seen checkpoints")
    r.add_argument("--dry-run", action="store_true", help="show what would be sent, call nothing")
    r.set_defaults(fn=cmd_run)

    m = sub.add_parser("models", help="list models your key can use")
    m.set_defaults(fn=cmd_models)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
