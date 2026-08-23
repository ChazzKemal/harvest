"""Push what was captured locally into the shared store.

Runs on each engineer's machine, after capture and after run. Signs in as that
engineer and writes only their own rows — RLS enforces the rest, so this file
does not have to be trusted to get the boundary right.

Incremental and safe to re-run: every row gets a content fingerprint, and
fingerprints already sent are recorded in out/.uploaded. Nothing is uploaded
twice, and an interrupted upload resumes where it stopped.

Silent no-op when Supabase is not configured. Solo machines keep working
exactly as before.
"""
from __future__ import annotations

import hashlib
import json
import uuid
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"


def _fingerprint(kind: str, row: dict) -> str:
    """Stable id for a row, so re-running never duplicates it.

    Content-based rather than a counter: claims.jsonl is rewritten when a
    session is re-reported, so line numbers move but the content does not.
    """
    row = {k: v for k, v in row.items() if k != "batch"}
    blob = json.dumps(row, sort_keys=True, default=str)
    return hashlib.sha256(f"{kind}:{blob}".encode()).hexdigest()[:32]


def _sent() -> set[str]:
    f = OUT / ".uploaded"
    return set(f.read_text().split()) if f.exists() else set()


def _record(fps: list[str]) -> None:
    with (OUT / ".uploaded").open("a") as f:
        for fp in fps:
            f.write(fp + "\n")


class _FileStorage:
    """The session written when someone signed in, shared with the tools.

    Both sides read the same file, so signing in once in a tool window is what
    authorises uploads from the hook. Nothing is stored in .env any more.
    """

    def __init__(self, path):
        self.path = path

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return {}

    def get_item(self, key: str):
        return self._read().get(key)

    def set_item(self, key: str, value: str) -> None:
        d = self._read()
        d[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(d))

    def remove_item(self, key: str) -> None:
        d = self._read()
        d.pop(key, None)
        self.path.write_text(json.dumps(d))


def _client():
    """Signed in as whoever used the tools, or None if nobody has."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY")
    if not (url and key):
        return None, None

    session_file = Path(os.environ.get("CUMULATE_HOME",
                                       Path.home() / ".cumulate")) / "session.json"
    if not session_file.exists():
        return None, None

    from supabase import ClientOptions, create_client

    c = create_client(url, key, options=ClientOptions(
        flow_type="pkce", storage=_FileStorage(session_file),
        persist_session=True, auto_refresh_token=True))
    session = c.auth.get_session()      # refreshes on its own when expired
    if not session:
        return None, None
    return c, session.user.id


def _jsonl(name: str) -> list[dict]:
    f = OUT / name
    if not f.exists():
        return []
    rows = []
    for line in f.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _tool_from_files(files: list) -> str:
    """Which tool a session touched, from its paths — same rule the reports use.

    Inferred asks record files rather than a tool, so without this every ask
    Harvest extracted would arrive with an empty tool and drop out of the
    admin view's tool filter entirely.
    """
    for path in files or []:
        parts = Path(str(path)).parts
        if len(parts) >= 2 and parts[0] == "tools":
            return parts[1]
    return ""


def _claim_row(c: dict, me: str, project: str) -> dict:
    return {"engineer": me, "session_id": c.get("session", ""), "type": c.get("type", ""),
            "claim": c.get("claim", ""), "evidence": c.get("evidence", ""),
            "why": c.get("why", ""), "confidence": c.get("confidence"),
            "generalises": bool(c.get("generalises")), "tool": c.get("tool") or "",
            "project": project, "claimed_on": c.get("date")}


def _correction_row(x: dict, me: str, project: str) -> dict:
    return {"engineer": me, "session_id": x.get("session", ""),
            "agent_assumed": x.get("agent_assumed", ""),
            "person_said": x.get("person_said", ""), "evidence": x.get("evidence", ""),
            "tool": x.get("tool") or "", "project": project, "corrected_on": x.get("date")}


def _asks_rows(raw: list[dict], me: str, project: str) -> list[dict]:
    """Flatten both shapes of asks.jsonl into one row per ask.

    Harvest writes one record per session holding a list of asks; the feature
    box in a tool writes one record per ask. Both land in the same table, told
    apart by `deliberate` — inferred asks are noisy and plentiful, typed ones
    are rare and worth far more.
    """
    out = []
    for r in raw:
        if "asks" in r:
            for a in r.get("asks", []):
                out.append({
                    "engineer": me, "session_id": r.get("session"), "ask": a,
                    "deliberate": False,
                    "tool": r.get("tool") or _tool_from_files(r.get("files", [])),
                    "project": project, "asked_on": r.get("date"),
                })
        elif r.get("ask"):
            out.append({
                "engineer": me, "session_id": r.get("session"), "ask": r["ask"],
                "deliberate": bool(r.get("deliberate")), "tool": r.get("tool") or "",
                "project": project, "asked_on": r.get("asked_on") or r.get("date"),
            })
    return out


# A very large diff is not worth the round trip — the record is meant to show
# what changed, not to be a second copy of the repository.
MAX_DIFF = 200_000


def _chat_files() -> list[Path]:
    d = OUT / "chats"
    return sorted(d.glob("*.json")) if d.exists() else []


def _chat_rows(me: str, project: str) -> list[dict]:
    rows = []
    for f in _chat_files():
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        sid = c.get("session_id") or c.get("checkpoint_id")
        if not sid:
            continue
        rows.append({
            "engineer": me, "session_id": sid,
            "agent": c.get("agent"), "model": c.get("model"),
            "tool": _tool_from_files(c.get("files", [])), "project": project,
            "started_at": c.get("started_at") or None,
            "duration_s": c.get("duration_s") or 0,
            "files": c.get("files", []), "commits": c.get("commits", []),
            "added": c.get("added") or 0, "removed": c.get("removed") or 0,
            "turns": c.get("turns", []), "diff": (c.get("diff") or "")[:MAX_DIFF],
        })
    return rows


# Chats change, unlike every other row here — so they need last-written state
# per session, not the ever-seen set. With a set, a chat restored to an earlier
# version matches an old hash and is skipped, leaving the store on the worse copy.
CHAT_STATE = "chat_state.json"


def _chat_state() -> dict:
    f = OUT / CHAT_STATE
    try:
        return json.loads(f.read_text())
    except Exception:
        return {}


def _push_chats(client, me: str, project: str) -> int:
    state = _chat_state()
    sent = 0
    for row in _chat_rows(me, project):
        sid = row["session_id"]
        fp = _fingerprint("chat", row)
        if state.get(sid) == fp:
            continue        # the store already holds exactly this
        try:
            client.table("chats").upsert(row, on_conflict="engineer,session_id").execute()
        except Exception as e:
            print(f"Upload: chats failed ({e}). Will retry next session.")
            break
        state[sid] = fp
        (OUT / CHAT_STATE).write_text(json.dumps(state))
        sent += 1
    return sent


def _me_offline() -> str:
    """The signed-in user's id, straight from the cached session.

    pending() has to fingerprint rows exactly as push() would, and the engineer
    id is part of that. Reading it from the cache keeps the count honest without
    a network call — otherwise everything already sent looks unsent.
    """
    p = Path(os.environ.get("CUMULATE_HOME", Path.home() / ".cumulate")) / "session.json"
    try:
        for v in json.loads(p.read_text()).values():
            user = (json.loads(v) or {}).get("user") or {}
            if user.get("id"):
                return user["id"]
    except Exception:
        pass
    return ""


def pending(project: str = "") -> dict:
    """What has not been sent yet. Counts only — no network needed, so the
    button can show a number even when someone is offline."""
    me = _me_offline()
    sent = _sent()
    claims = [c for c in _jsonl("claims.jsonl")
              if _fingerprint("claim", _claim_row(c, me, project)) not in sent]
    corrections = [x for x in _jsonl("corrections.jsonl")
                   if _fingerprint("correction", _correction_row(x, me, project)) not in sent]
    asks = [a for a in _asks_rows(_jsonl("asks.jsonl"), me, project)
            if _fingerprint("ask", a) not in sent]
    state = _chat_state()
    chats = [r for r in _chat_rows(me, project)
             if state.get(r["session_id"]) != _fingerprint("chat", r)]
    return {"sessions": len(chats), "claims": len(claims),
            "corrections": len(corrections), "asks": len(asks)}


def push(project: str = "", quiet: bool = False) -> int:
    """Send anything not yet sent. Returns rows uploaded."""
    try:
        client, me = _client()
    except Exception as e:
        if not quiet:
            print(f"Upload: couldn't sign in ({e}). Captured locally, will retry.")
        return 0
    if client is None:
        return 0

    sent = _sent()
    total = 0

    # One batch per run: the views show the newest, so a re-extraction supersedes
    # its predecessor instead of sitting alongside it.
    batch = str(uuid.uuid4())
    claims = [{**_claim_row(c, me, project), "batch": batch}
              for c in _jsonl("claims.jsonl")]

    corrections = [{**_correction_row(x, me, project), "batch": batch}
                   for x in _jsonl("corrections.jsonl")]

    asks = _asks_rows(_jsonl("asks.jsonl"), me, project)

    # Chats are upserted rather than fingerprinted: a session reported mid-flight
    # later gains its commits and diff, so the same session_id must be allowed to
    # come back with more in it. Fingerprints would leave both copies.
    total += _push_chats(client, me, project)

    for kind, rows in (("claim", claims), ("correction", corrections), ("ask", asks)):
        fresh, fps = [], []
        for r in rows:
            fp = _fingerprint(kind, r)
            if fp not in sent:
                fresh.append(r)
                fps.append(fp)
        if not fresh:
            continue
        table = {"claim": "claims", "correction": "corrections", "ask": "asks"}[kind]
        # Batched, and only marked as sent once the insert actually returned —
        # a crash mid-upload re-sends a batch rather than losing it.
        for i in range(0, len(fresh), 200):
            chunk, chunk_fps = fresh[i:i + 200], fps[i:i + 200]
            try:
                client.table(table).insert(chunk).execute()
            except Exception as e:
                if not quiet:
                    print(f"Upload: {table} failed ({e}). Will retry next session.")
                break
            _record(chunk_fps)
            total += len(chunk)

    if total and not quiet:
        print(f"Upload: {total} row(s) sent.")
    return total
