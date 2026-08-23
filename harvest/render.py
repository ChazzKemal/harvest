"""Claims -> a page someone will actually read."""
from __future__ import annotations

TYPE_LABELS = {
    "data_semantics": "What the data actually means",
    "hygiene_rule": "Data hygiene",
    "implicit_constraint": "Constraints nobody modelled",
    "objective_tradeoff": "What good looks like",
    "acceptance_heuristic": "How they judge an answer",
    "exception_override": "Manual overrides",
    "vocabulary": "Vocabulary",
}
ORDER = ["acceptance_heuristic", "exception_override", "implicit_constraint",
         "objective_tradeoff", "data_semantics", "hygiene_rule", "vocabulary"]


def to_markdown(sess, r: dict) -> str:
    L: list[str] = [f"# {r.get('headline', 'Session')}", ""]

    meta = [x for x in (sess.agent, sess.model, sess.started_at[:16] if sess.started_at else "") if x]
    if meta:
        L += [" · ".join(meta), ""]
    L += [r.get("what_was_built", ""), ""]

    if corr := r.get("corrections"):
        L += ["## Corrections", "",
              "_Where the agent was wrong and the engineer put it right. Highest-value part._", ""]
        for c in corr:
            L += [f"- **Agent assumed:** {c['agent_assumed']}",
                  f"  **They said:** {c['person_said']}",
                  f"  > {c['evidence'].strip()}", ""]

    claims = r.get("claims", [])
    if claims:
        L += ["## What they know", ""]
        for t in ORDER:
            group = [c for c in claims if c.get("type") == t]
            if not group:
                continue
            L += [f"### {TYPE_LABELS.get(t, t)}", ""]
            for c in group:
                flags = [c.get("confidence", "")]
                if not c.get("generalises", True):
                    flags.append("this file only")
                L.append(f"- {c['claim']}  `{' · '.join(f for f in flags if f)}`")
                if why := c.get("why"):
                    L.append(f"  **Why:** {why}")
                L += [f"  > {c['evidence'].strip()}", ""]
    else:
        L += ["## What they know", "",
              "_Nothing surfaced in this session. That is a real result, not a failure —"
              " most sessions where the agent got it right first time will look like this._", ""]

    if q := r.get("open_questions"):
        L += ["## Left open", ""] + [f"- {x}" for x in q] + [""]

    L += ["---", f"Checkpoint `{sess.checkpoint_id}`"
          + (f" · session `{sess.session_id}`" if sess.session_id else "")]
    if sess.files:
        L.append(f"Files touched: {', '.join(sess.files[:12])}")
    return "\n".join(L) + "\n"
