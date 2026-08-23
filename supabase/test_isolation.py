"""Prove an engineer cannot read anyone else's knowledge.

A wrong RLS policy fails silently and looks exactly like a right one until the
day someone runs a query. This makes it loud instead: two throwaway engineers,
a row each, then assert that neither can see the other's.

    python supabase/test_isolation.py

Needs SUPABASE_URL and SUPABASE_SECRET_KEY in Harvest/.env. Creates two users
named test-isolation-*, and deletes them at the end even if it fails.
"""
from __future__ import annotations

import os
import sys
import uuid

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
URL = os.environ.get("SUPABASE_URL")
SECRET = os.environ.get("SUPABASE_SECRET_KEY")
PUBLISHABLE = os.environ.get("SUPABASE_PUBLISHABLE_KEY")

if not (URL and SECRET and PUBLISHABLE):
    sys.exit("Set SUPABASE_URL, SUPABASE_SECRET_KEY and SUPABASE_PUBLISHABLE_KEY in .env")

admin = create_client(URL, SECRET)
failures: list[str] = []
made: list[str] = []


def make(tag: str) -> tuple[str, str, str]:
    """An engineer, provisioned the same way a real one is."""
    email = f"test-isolation-{tag}-{uuid.uuid4().hex[:8]}@example.invalid"
    password = uuid.uuid4().hex
    user = admin.auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": True}
    ).user
    made.append(user.id)
    admin.table("engineers").insert(
        {"id": user.id, "name": f"isolation {tag}", "email": email}
    ).execute()
    return user.id, email, password


def as_engineer(email: str, password: str):
    """A client holding only what a real engineer's machine holds."""
    c = create_client(URL, PUBLISHABLE)
    c.auth.sign_in_with_password({"email": email, "password": password})
    return c


def check(name: str, ok: bool) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        failures.append(name)


try:
    a_id, a_email, a_pw = make("a")
    b_id, b_email, b_pw = make("b")

    secret_claim = f"secret-of-a-{uuid.uuid4().hex[:8]}"
    admin.table("claims").insert([
        {"engineer": a_id, "session_id": "s-a", "type": "vocabulary",
         "claim": secret_claim, "tool": "tool-a"},
        {"engineer": b_id, "session_id": "s-b", "type": "vocabulary",
         "claim": "secret-of-b", "tool": "tool-b"},
    ]).execute()

    a = as_engineer(a_email, a_pw)
    b = as_engineer(b_email, b_pw)

    print("\nreading:")
    a_sees = [r["claim"] for r in a.table("claims").select("claim").execute().data]
    check("A sees its own claim", secret_claim in a_sees)
    check("A cannot see B's claim", "secret-of-b" not in a_sees)

    b_sees = [r["claim"] for r in b.table("claims").select("claim").execute().data]
    check("B cannot see A's claim", secret_claim not in b_sees)

    # The filter is a value the client sends, so it must not be trusted as a
    # boundary. Asking explicitly for someone else's rows must still return none.
    targeted = a.table("claims").select("claim").eq("engineer", b_id).execute().data
    check("A cannot read B's rows by asking for them directly", targeted == [])

    print("\nwriting:")
    try:
        a.table("claims").insert(
            {"engineer": b_id, "session_id": "forged", "type": "vocabulary",
             "claim": "written by A, attributed to B"}
        ).execute()
        check("A cannot write a row attributed to B", False)
    except Exception:
        check("A cannot write a row attributed to B", True)

    print("\nappend-only:")
    try:
        a.table("claims").delete().eq("engineer", a_id).execute()
        left = a.table("claims").select("claim").execute().data
        check("A cannot delete its own history", len(left) > 0)
    except Exception:
        check("A cannot delete its own history", True)

    print("\nadmin:")
    all_claims = [r["claim"] for r in admin.table("claims").select("claim").execute().data]
    check("secret key sees both", secret_claim in all_claims and "secret-of-b" in all_claims)

finally:
    for uid in made:
        try:
            admin.auth.admin.delete_user(uid)
        except Exception:
            print(f"  (couldn't clean up {uid} — delete it by hand)")

print()
if failures:
    sys.exit(f"{len(failures)} FAILED: {', '.join(failures)}\nDo not put real data in until these pass.")
print("Isolation holds.")
