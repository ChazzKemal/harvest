"""What a captured session carries: its conversation, what changed, and the code.

Builds a throwaway Codex store and workspace, so it runs anywhere:
    python -m unittest discover tests
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from harvest import codex_store, snapshot


class CaptureCode(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = (self.tmp / "Workspace").resolve()
        (self.repo / "tools" / "rates").mkdir(parents=True)
        (self.repo / "inbox").mkdir()
        self.codex = self.tmp / "codex"
        (self.codex / "sessions").mkdir(parents=True)
        self.db = sqlite3.connect(self.codex / "thread_history_1.sqlite")
        self.db.execute("create table thread_items (thread_id text, item_type text, item_json text,"
                        " created_at_ms integer, rollout_ordinal integer)")
        self._old = codex_store.CODEX_DIR
        codex_store.CODEX_DIR = self.codex
        self.n = 0

    def tearDown(self):
        codex_store.CODEX_DIR = self._old
        self.db.close()

    def write(self, rel: str, text: str):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def session(self, tid: str, items: list[tuple[str, dict]], started_in: Path | None = None):
        now = int(time.time() * 1000)
        for kind, body in items:
            self.n += 1
            self.db.execute("insert into thread_items values (?,?,?,?,?)",
                            (tid, kind, json.dumps(body), now, self.n))
        self.db.commit()
        if started_in:
            meta = {"type": "session_meta", "payload": {"id": tid, "cwd": str(started_in)}}
            (self.codex / "sessions" / f"rollout-x-{tid}.jsonl").write_text(json.dumps(meta) + "\n")

    def edit(self, rel: str, kind: str, diff: str) -> tuple[str, dict]:
        # Codex records absolute, OS-native paths.
        return ("fileChange", {"changes": [{"path": str(self.repo / Path(rel)), "kind": {"type": kind},
                                            "diff": diff}]})

    def found(self):
        return {s.session_id: s for s in codex_store.sessions_for(self.repo, 1)}

    # ------------------------------------------------------------------------

    def test_a_script_straight_under_tools_is_kept_with_its_diff(self):
        self.write("tools/convert.py", "print('hi')\n")
        self.session("t1", [("userMessage", {"text": "make a converter"}),
                            self.edit("tools/convert.py", "add", "print('hi')\n")])
        s = self.found()["t1"]
        self.assertEqual(s.files, ["tools/convert.py"])            # forward slashes
        self.assertIn("tools/convert.py", s.sources)
        self.assertIn("+++ b/tools/convert.py", s.diff)
        self.assertIn("+print('hi')", s.diff)

    def test_a_tool_folder_is_kept_whole_but_never_its_data(self):
        self.write("tools/rates/app.py", "x = 1\n")
        self.write("tools/rates/ASSUMPTIONS.md", "rates are net\n")
        self.write("tools/rates/sample.csv", "name,salary\nali,100\n")
        self.write("tools/rates/model.ifc", "ISO-10303-21;\n")
        self.session("t2", [("userMessage", {"text": "rates tool"}),
                            self.edit("tools/rates/app.py", "update", "@@ -1 +1 @@\n-x = 0\n+x = 1")])
        src = self.found()["t2"].sources
        self.assertIn("tools/rates/app.py", src)
        self.assertIn("tools/rates/ASSUMPTIONS.md", src)
        self.assertNotIn("tools/rates/sample.csv", src)
        self.assertNotIn("tools/rates/model.ifc", src)

    def test_edits_to_data_or_the_inbox_never_travel(self):
        self.write("inbox/notes.md", "private\n")
        self.write("tools/out.csv", "a,b\n")
        self.session("t3", [("userMessage", {"text": "tidy up"}),
                            self.edit("inbox/notes.md", "update", "@@ -1 +1 @@\n-x\n+private"),
                            self.edit("tools/out.csv", "add", "a,b\n")])
        s = self.found()["t3"]
        self.assertEqual(s.sources, {})
        self.assertEqual(s.diff, "")
        self.assertNotIn("private", json.dumps(s.turns + [s.diff, s.sources]))

    def test_a_conversation_without_commands_or_edits_still_counts(self):
        self.session("t4", [("userMessage", {"text": "how should I round these rates?"}),
                            ("agentMessage", {"text": "Half up, to two places."})],
                     started_in=self.repo)
        s = self.found()["t4"]
        self.assertEqual([t["role"] for t in s.turns], ["user", "assistant"])

    def test_a_session_elsewhere_is_not_ours(self):
        self.session("t5", [("userMessage", {"text": "other project"})], started_in=self.tmp / "elsewhere")
        self.assertNotIn("t5", self.found())

    def test_opened_and_closed_with_only_the_greeting_is_skipped(self):
        self.session("t6", [("userMessage", {"text": codex_store.LAUNCH_PROMPT + " Greet me."}),
                            ("agentMessage", {"text": "Hi!"})], started_in=self.repo)
        self.assertNotIn("t6", self.found())

    def test_shareable(self):
        for ok in ("tools/a.py", "tools/x/README.md", "requirements.txt", "tools/run.bat"):
            self.assertTrue(snapshot.shareable(ok), ok)
        for no in ("tools/a.xlsx", "tools/a.csv", "inbox/a.py", "projects/b.md", ".env",
                   "tools/model.ifc", "tools/mesh.obj", "tools/data.json"):
            self.assertFalse(snapshot.shareable(no), no)


if __name__ == "__main__":
    unittest.main()
