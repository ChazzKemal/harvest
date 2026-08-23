"""Browse what has been harvested. Run with ./view.command"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import streamlit as st

OUT = Path(__file__).resolve().parent.parent / "out"

TYPE_LABELS = {
    "data_semantics": "What the data means",
    "hygiene_rule": "Data hygiene",
    "implicit_constraint": "Unmodelled constraints",
    "objective_tradeoff": "What good looks like",
    "acceptance_heuristic": "How they judge an answer",
    "exception_override": "Manual overrides",
    "vocabulary": "Vocabulary",
}


def _jsonl(name: str) -> list[dict]:
    f = OUT / name
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def _reports() -> list[tuple[Path, str, str]]:
    out = []
    for f in sorted((OUT / "sessions").glob("*.md"), reverse=True):
        text = f.read_text()
        m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        out.append((f, m.group(1) if m else f.stem, text))
    return out


st.set_page_config(page_title="Harvest", layout="wide")
st.title("Harvest")
st.caption("What your engineers know, taken from their sessions.")

claims, asks, reports = _jsonl("claims.jsonl"), _jsonl("asks.jsonl"), _reports()

if not reports and not claims:
    st.info("Nothing harvested yet. Run a session in the Tool Builder, then "
            "`python -m harvest run --repo ../Cumulate`.")
    st.stop()

a, b, c, d = st.columns(4)
a.metric("Sessions", len(reports))
b.metric("Claims", len(claims))
c.metric("Generalise", sum(1 for x in claims if x.get("generalises")))
d.metric("Asks recorded", len(asks))

tab_claims, tab_sessions, tab_asks = st.tabs(["Knowledge", "Sessions", "What people asked for"])

with tab_claims:
    if not claims:
        st.info("No claims yet.")
    else:
        left, right = st.columns([1, 3])
        with left:
            kinds = sorted({x["type"] for x in claims})
            pick = st.multiselect("Type", kinds, default=kinds,
                                  format_func=lambda k: TYPE_LABELS.get(k, k))
            conf = st.multiselect("Confidence", ["stated", "implied", "inferred"],
                                  default=["stated", "implied", "inferred"])
            only_general = st.checkbox("Only claims that generalise", value=False)

        rows = [x for x in claims
                if x["type"] in pick and x.get("confidence") in conf
                and (x.get("generalises") or not only_general)]

        with right:
            st.write(f"**{len(rows)} of {len(claims)} claims**")
            for kind in [k for k in TYPE_LABELS if any(r["type"] == k for r in rows)]:
                st.subheader(TYPE_LABELS[kind])
                for r in [x for x in rows if x["type"] == kind]:
                    scope = "" if r.get("generalises") else " · this file only"
                    st.markdown(f"**{r['claim']}**  \n"
                                f"`{r.get('confidence','')}{scope}` · {r.get('date','')}")
                    if r.get("why"):
                        st.markdown(f"*Why:* {r['why']}")
                    st.caption(f"“{r.get('evidence','').strip()}”")
                    st.divider()

with tab_sessions:
    if not reports:
        st.info("No session reports yet.")
    else:
        names = [f"{f.stem[:10]} — {title}" for f, title, _ in reports]
        i = st.radio("Session", range(len(names)), format_func=lambda i: names[i],
                     label_visibility="collapsed")
        st.markdown(reports[i][2])

with tab_asks:
    if not asks:
        st.info("Nothing recorded yet.")
    else:
        st.caption("Every real request, whether or not it was worth extracting from. "
                   "This is what people actually want built.")
        for a_ in reversed(asks):
            with st.container(border=True):
                st.markdown(f"**{a_.get('date','')}** · "
                            f"{'extracted' if a_.get('extracted') else 'not extracted'} · "
                            f"{a_.get('words',0)} words")
                for q in a_.get("asks", []):
                    st.markdown(f"> {q}")
                if a_.get("files"):
                    st.caption("Files: " + ", ".join(a_["files"][:8]))
