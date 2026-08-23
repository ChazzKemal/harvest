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

from . import adminpage, chats, codex_store, sources, store, upload
from .extract import extract
from . import page as pagegen
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


def _tool_of(sess) -> str:
    """Which tool this session worked on, from the paths it touched."""
    for f in sess.files:
        parts = Path(f).parts
        if len(parts) >= 2 and parts[0] == "tools":
            return parts[1]
    return ""


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
                                "tool": _tool_of(sess),
                                "agent": sess.agent, "date": stamp}) + "\n")
    # Corrections were only ever rendered into the markdown report, which means
    # they could not be filtered, counted or compared across sessions. They are
    # the clearest signal of where someone got stuck, so keep them as data too.
    xf = OUT / "corrections.jsonl"
    kept_x = [l for l in xf.read_text().splitlines() if l.strip()
              and json.loads(l).get("session") != key] if xf.exists() else []
    with xf.open("w") as f:
        for line in kept_x:
            f.write(line + "\n")
        for x in result.get("corrections", []):
            f.write(json.dumps({**x, "session": key,
                                "checkpoint": sess.checkpoint_id,
                                "tool": _tool_of(sess),
                                "agent": sess.agent, "date": stamp}) + "\n")
    return path


def _gather(repo: Path, since: str, source: str = "both") -> list:
    """Every session for this repo, from both sources, merged.

    The two sources are complementary, not redundant: Entire has the commit and
    the diff, Codex has the structured turns. Taking one and discarding the other
    loses half the session.
    """
    found: list = []
    if source in ("entire", "both"):
        found += sources.sessions(repo, since)
    if source in ("codex", "both"):
        days = int("".join(c for c in since if c.isdigit()) or 30)
        found += codex_store.sessions_for(repo, days)
    return _merge(found)


def _merge(found: list) -> list:
    """Fold sessions sharing an id into one, keeping the best of each field."""
    by_id: dict = {}
    for s in found:
        key = s.session_id or s.checkpoint_id
        prev = by_id.get(key)
        if prev is None:
            by_id[key] = s
            continue
        # Prefer real structured turns, a real commit, and the longer transcript.
        prev.turns = prev.turns or s.turns
        prev.commits = prev.commits or s.commits
        prev.diff = prev.diff if len(prev.diff) >= len(s.diff) else s.diff
        if len(s.transcript) > len(prev.transcript):
            prev.transcript = s.transcript
        prev.prompts = prev.prompts or s.prompts
        prev.model = prev.model or s.model
        prev.agent = prev.agent or s.agent
        prev.started_at = min(x for x in (prev.started_at, s.started_at) if x) \
            if (prev.started_at and s.started_at) else (prev.started_at or s.started_at)
        prev.files = sorted(set(prev.files) | set(s.files))
        prev.tokens = prev.tokens or s.tokens
        prev.author = prev.author or s.author
        prev.checkpoint_count = prev.checkpoint_count or s.checkpoint_count
        prev.added = prev.added or s.added
        prev.removed = prev.removed or s.removed
        # Entire's checkpoint id is the durable one; keep it over "codex:..."
        if s.checkpoint_id and not s.checkpoint_id.startswith("codex:"):
            prev.checkpoint_id = s.checkpoint_id
    return list(by_id.values())


def cmd_capture(args) -> int:
    """Keep every conversation. Free — no model is called."""
    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        print(f"Not a git repo: {repo}", file=sys.stderr)
        return 1

    live = sources.active_sessions(repo)
    if args.ended:
        live.discard(args.ended)

    saved = skipped = 0
    for sess in _gather(repo, args.since, "both"):
        if sess.session_id in live:
            skipped += 1
            continue
        _, changed = chats.save(OUT, sess)
        saved += 1 if changed else 0

    total = len(chats.load_all(OUT))
    note = f", {skipped} still running" if skipped else ""
    print(f"Chats: {saved} new or updated, {total} kept in total{note}.")
    upload.push(project=Path(args.repo).resolve().name)
    pagegen.build(OUT)
    return 0


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

    candidates = _gather(repo, args.since, args.source)

    live = sources.active_sessions(repo)
    if args.ended:
        live.discard(args.ended)

    saved = skipped = 0
    for sess in _gather(repo, args.since, "both"):
        if sess.session_id in live:
            skipped += 1
            continue
        _, changed = chats.save(OUT, sess)
        saved += 1 if changed else 0

    total = len(chats.load_all(OUT))
    note = f", {skipped} still running" if skipped else ""
    print(f"Chats: {saved} new or updated, {total} kept in total{note}.")
    upload.push(project=Path(args.repo).resolve().name)
    pagegen.build(OUT)
    return 0


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
        chats.save(OUT, sess)
        result = extract(sess.transcript, sess.diff, sources.git_log(repo), model_name=args.model)
        print(f"  {cid[:18]} — {len(result.get('claims', []))} claims, "
              f"{len(result.get('corrections', []))} corrections -> {_write(sess, result, _slug(sess)).name}")
        _mark(sess)
        done += 1

    if not args.dry_run and OUT.exists():
        # After extraction, not before: upload what this run actually produced.
        # Never on a dry run — that promises to spend nothing and change nothing.
        upload.push(project=repo.name)
        pagegen.build(OUT)

    if done and args.dry_run:
        print(f"\n{done} session(s) would be sent, {skipped} skipped without spending.")
    elif done:
        print(f"\n{done} session(s) processed, {skipped} skipped without spending. "
              f"Claims appended to out/claims.jsonl")
    else:
        print(f"\nNothing worth extracting. {skipped} session(s) skipped, no API calls made.\n"
              f"What people asked for is still recorded in out/asks.jsonl.")
    return 0


def cmd_weekly(args) -> int:
    """The deliberate pass: summarise what actually got committed this week."""
    args.source, args.working, args.force = "both", False, False
    args.dry_run, args.ended, args.min_words = False, None, 3
    repo = Path(args.repo).resolve()
    cutoff = {s.session_id for s in _gather(repo, args.since, "both") if s.commits}
    if not cutoff:
        print(f"Nothing committed in the last {args.since}. Chats are still kept.")
        return 0
    print(f"{len(cutoff)} session(s) with commits in the last {args.since}.")
    return cmd_run(args)


def cmd_page(_args) -> int:
    p = pagegen.build(OUT)
    print(f"Wrote {p}")
    return 0


def cmd_extract(args) -> int:
    """Extract from the shared store: everyone's sessions, on your key, here.

    The counterpart to `run`. `run` reads this machine's own sessions; this reads
    what everyone has uploaded, so a person never needs a key to have their work
    understood — only to talk to the agent in the first place.
    """
    _load_env()
    c = store.client()

    done = store.already_extracted(c) if not args.force else set()
    rows = store.sessions(c)
    batch = store.new_batch()

    todo = [(s_, eng, proj) for s_, eng, proj in rows if s_.session_id not in done]
    if not todo:
        print(f"Nothing new. {len(rows)} session(s) in the store, all extracted.")
        return 0

    print(f"{len(todo)} session(s) not yet extracted, of {len(rows)} in the store.\n")
    claims = corrections = spent = skipped = 0
    for sess, engineer, project in todo:
        decision = assess(sess, min_words=args.min_words)
        label = sess.session_id[:12]
        if not decision.run and not args.force:
            print(f"  {label} — skipped: {decision}")
            skipped += 1
            continue
        if args.dry_run:
            print(f"  {label} — would send: {decision}, "
                  f"{len(sess.transcript)} chars transcript, {len(sess.diff)} chars diff")
            spent += 1
            continue
        result = extract(sess.transcript, sess.diff, "", model_name=args.model)
        tool = _tool_of(sess)
        n_c, n_x = store.write_back(c, sess, engineer, project, tool, result, batch)
        claims += n_c
        corrections += n_x
        spent += 1
        print(f"  {label} — {n_c} claims, {n_x} corrections")

    if args.dry_run:
        print(f"\n{spent} session(s) would be sent, {skipped} skipped without spending.")
    else:
        print(f"\n{spent} session(s) extracted, {skipped} skipped. "
              f"{claims} claims, {corrections} corrections written back.")
    return 0


def cmd_admin(_args) -> int:
    """The whole record, everyone's, as one page. Yours only."""
    _load_env()
    if not os.environ.get("SUPABASE_SECRET_KEY"):
        print("Set SUPABASE_SECRET_KEY in Harvest/.env first.")
        return 1
    OUT.mkdir(exist_ok=True)
    path = adminpage.build(OUT)
    print(f"Written to {path}")
    return 0


def cmd_upload(args) -> int:
    """Backfill. Everything already sent is skipped by fingerprint."""
    n = upload.push(project=Path(args.repo).resolve().name)
    if not n:
        print("Nothing new to send." if os.environ.get("SUPABASE_URL")
              else "Sharing isn't set up on this machine.")
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

    c = sub.add_parser("capture", help="keep every conversation (free, no model call)")
    c.add_argument("--repo", required=True)
    c.add_argument("--since", default="30d")
    c.add_argument("--ended", default=None,
                   help="session id the hook says just finished")
    c.set_defaults(fn=cmd_capture)

    w = sub.add_parser("weekly", help="summarise the last week's committed work")
    w.add_argument("--repo", required=True)
    w.add_argument("--since", default="7d")
    w.add_argument("--model", default=None)
    w.add_argument("--committed-only", action="store_true", default=True)
    w.set_defaults(fn=cmd_weekly)

    g = sub.add_parser("page", help="rebuild out/index.html from what is already there")
    g.set_defaults(fn=cmd_page)

    u = sub.add_parser("upload", help="send captured knowledge to the shared store")
    u.add_argument("--repo", default="../Cumulate", help="repo the sessions came from")
    u.set_defaults(fn=cmd_upload)

    e = sub.add_parser("extract", help="extract from everyone's uploaded sessions (your key)")
    e.add_argument("--dry-run", action="store_true", help="show what would be sent, spend nothing")
    e.add_argument("--force", action="store_true", help="re-extract sessions already done")
    e.add_argument("--model", default=None)
    e.add_argument("--min-words", type=int, default=3)
    e.set_defaults(fn=cmd_extract)

    ad = sub.add_parser("admin", help="build the everyone-view page")
    ad.set_defaults(fn=cmd_admin)

    m = sub.add_parser("models", help="list models your key can use")
    m.set_defaults(fn=cmd_models)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
