"""Read sessions back out of the shared store, so extraction can run in one place.

Capture is free and happens on everyone's machine. Extraction costs money, and
until now it had to run wherever the raw session lived — which meant a key on
every machine. Uploading the transcripts changed that: the material is central,
so the spending can be too.

Uses the secret key. It reads everyone's chats and writes claims back attributed
to the person they came from, which no signed-in engineer could do.
"""
from __future__ import annotations

import os
import uuid

from .sources import Session


def client():
    from supabase import create_client

    url, secret = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SECRET_KEY")
    if not (url and secret):
        raise SystemExit("Set SUPABASE_URL and SUPABASE_SECRET_KEY in Harvest/.env")
    return create_client(url, secret)


def _transcript(turns: list[dict]) -> str:
    """The same [User]/[Assistant]/[Tool] rendering the local path produces, so
    the model sees one shape of input wherever the session came from."""
    out = []
    for t in turns or []:
        role = (t.get("role") or "").lower()
        label = {"user": "User", "assistant": "Assistant",
                 "tool": "Tool", "reasoning": "Reasoning"}.get(role, role.title())
        text = (t.get("text") or "").strip()
        if text:
            out.append(f"[{label}] {text}")
    return "\n\n".join(out)


def sessions(c, since_days: int | None = None) -> list[tuple[Session, str, str]]:
    """Every uploaded chat as (Session, engineer_id, project)."""
    rows = c.table("chats").select("*").order("started_at", desc=True).execute().data
    out = []
    for r in rows:
        turns = r.get("turns") or []
        sess = Session(
            checkpoint_id=r.get("session_id", ""),
            session_id=r.get("session_id", ""),
            agent=r.get("agent") or "",
            model=r.get("model") or "",
            started_at=(r.get("started_at") or "")[:19],
            prompts=[t.get("text", "") for t in turns if t.get("role") == "user"],
            transcript=_transcript(turns),
            diff=r.get("diff") or "",
            commits=r.get("commits") or [],
            files=r.get("files") or [],
            turns=turns,
            added=r.get("added") or 0,
            removed=r.get("removed") or 0,
        )
        out.append((sess, r["engineer"], r.get("project") or ""))
    return out


def already_extracted(c) -> set[str]:
    """Sessions that already have claims. Re-extracting one costs money and
    produces the same thing, so it is skipped unless forced."""
    return {r["session_id"] for r in c.table("claims").select("session_id").execute().data}


def write_back(c, sess, engineer: str, project: str, tool: str,
               result: dict, batch: str) -> tuple[int, int]:
    """Put what was extracted back, attributed to whoever did the work."""
    date = (sess.started_at or "")[:10] or None
    claims = [{
        "engineer": engineer, "session_id": sess.session_id, "type": x.get("type", ""),
        "claim": x.get("claim", ""), "evidence": x.get("evidence", ""),
        "why": x.get("why", ""), "confidence": x.get("confidence"),
        "generalises": bool(x.get("generalises")), "tool": tool, "project": project,
        "claimed_on": date, "batch": batch,
    } for x in result.get("claims", [])]

    corrections = [{
        "engineer": engineer, "session_id": sess.session_id,
        "agent_assumed": x.get("agent_assumed", ""), "person_said": x.get("person_said", ""),
        "evidence": x.get("evidence", ""), "tool": tool, "project": project,
        "corrected_on": date, "batch": batch,
    } for x in result.get("corrections", [])]

    if claims:
        c.table("claims").insert(claims).execute()
    if corrections:
        c.table("corrections").insert(corrections).execute()
    return len(claims), len(corrections)


def new_batch() -> str:
    return str(uuid.uuid4())
