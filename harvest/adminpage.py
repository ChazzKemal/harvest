"""The admin record as one self-contained dark page — everything, from everyone.

Same shape and palette as out/index.html, because that page reads well and a
second look-and-feel for the same material would be a step backwards. What it
adds is the filtering the shared store makes possible: by person, by tool, by
project, on top of the type and confidence filters the engineer view already has.

Reads Supabase with the secret key, so it sees past every row-level policy.
Never share the file it writes — it contains everyone's knowledge.
"""
from __future__ import annotations

import html
import os
from collections import Counter
from pathlib import Path

from .labels import TYPE_LABELS
from .page import CSS, _ago, _dur, _thread

EXTRA_CSS = """
.diff{font-family:var(--mono);font-size:12px;line-height:1.5;background:var(--bg);
      border:1px solid var(--line);border-radius:8px;padding:12px 14px;overflow-x:auto;
      max-height:460px;overflow-y:auto;white-space:pre}
.diff .add{color:var(--green)} .diff .del{color:var(--red)} .diff .hd{color:var(--blue)}
.sess summary{cursor:pointer;list-style:none}
.sess summary::-webkit-details-marker{display:none}
.sess[open] summary{margin-bottom:14px}
.subtabs{display:flex;gap:18px;border-bottom:1px solid var(--line);margin:4px 0 14px}
.subtab{color:var(--muted);font-size:12.5px;padding:5px 0;cursor:pointer;border-bottom:2px solid transparent}
.subtab.on{color:var(--fg);border-bottom-color:var(--accent)}
.who{color:var(--accent)}
.rowhead{display:flex;align-items:center;gap:9px;margin-bottom:9px;flex-wrap:wrap}
.chip{font-family:var(--mono);font-size:10.5px;padding:2px 7px;border-radius:4px;
      background:var(--raised);color:var(--muted);border:1px solid var(--line)}
.chip.on{color:var(--accent);border-color:rgba(217,119,87,.28)}
.said{color:var(--fg);font-size:13.5px;margin-top:3px}
.said b{color:var(--accent);font-weight:500}
.assumed{color:var(--muted);font-size:13px}
.bar{display:flex;align-items:center;gap:9px;margin:4px 0;font-size:12.5px;color:var(--muted)}
.bar .track{flex:1;height:6px;background:var(--raised);border-radius:3px;overflow:hidden}
.bar .fill{height:100%;background:var(--accent);opacity:.75}
.bar .lab{width:150px;color:var(--fg);font-size:12.5px}
.bar .n{width:28px;text-align:right;font-variant-numeric:tabular-nums}
.none{display:none !important}
"""

JS = """
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
function show(view){
  $$('.view').forEach(v=>v.classList.toggle('hide', v.id!=='v-'+view));
  $$('.nav').forEach(n=>n.classList.toggle('on', n.dataset.view===view));
  $('#crumb').textContent = $(`.nav[data-view="${view}"]`).dataset.label;
  $('#rail-knowledge').classList.toggle('hide', view!=='knowledge');
  filter();
}
function picked(cls){
  const on = $$('.'+cls).filter(i=>i.checked).map(i=>i.value);
  // Nothing ticked means no constraint, not "show nothing" — otherwise
  // clearing a filter blanks the page and looks broken.
  return on.length ? on : null;
}
function filter(){
  const who=picked('fwho'), tool=picked('ftool'), proj=picked('fproj'),
        type=picked('ftype'), conf=picked('fconf'), gen=$('#fgen').checked;
  $$('.card[data-who]').forEach(c=>{
    let ok = (!who  || who.includes(c.dataset.who))
          && (!tool || tool.includes(c.dataset.tool))
          && (!proj || proj.includes(c.dataset.proj));
    if(ok && c.dataset.type) ok = !type || type.includes(c.dataset.type);
    if(ok && c.dataset.conf) ok = !conf || conf.includes(c.dataset.conf);
    if(ok && gen && c.dataset.gen!=='1') ok = false;
    c.classList.toggle('none', !ok);
  });
  $$('.group').forEach(g=>{
    const n = $$('.card:not(.none)', g).length;
    g.classList.toggle('none', n===0);
    const c = $('.gcount', g); if(c) c.textContent = n;
  });
  $$('.view').forEach(v=>{
    const n = $$('.card:not(.none)', v).length;
    const e = $('.empty', v); if(e) e.classList.toggle('none', n>0);
    const t = $('.vcount', v); if(t) t.textContent = n;
  });
}
$$('.nav').forEach(n=>n.onclick=()=>show(n.dataset.view));
$$('.fwho,.ftool,.fproj,.ftype,.fconf,#fgen').forEach(i=>i.onchange=filter);
$$('.gtoggle').forEach(t=>t.onclick=()=>t.parentElement.classList.toggle('shut'));
// Conversation / what changed, per session.
$$('.subtab').forEach(t=>t.onclick=e=>{
  e.preventDefault(); e.stopPropagation();
  const card=t.closest('.sess');
  $$('.subtab',card).forEach(x=>x.classList.toggle('on', x===t));
  $$('.pane',card).forEach(p=>p.classList.toggle('hide', !p.classList.contains('pane-'+t.dataset.pane)));
});
show('sessions');
"""


def _e(v) -> str:
    return html.escape(str(v or ""))


def _latest_batch(rows: list[dict]) -> list[dict]:
    """Keep each session's most recent extraction, drop the superseded ones."""
    newest: dict[str, str] = {}
    for r in rows:
        sid, when = r.get("session_id"), r.get("created_at") or ""
        if when > newest.get(sid, ""):
            newest[sid] = when
    keep = {r.get("batch") for r in rows
            if (r.get("created_at") or "") == newest.get(r.get("session_id"))}
    # Rows predating batches have none. Keep them only for sessions that have no
    # batched rows at all — once a session has been extracted since, the older
    # unbatched rows are exactly the superseded ones we are trying to hide.
    batched = {r.get("session_id") for r in rows if r.get("batch")}
    return [r for r in rows
            if (r.get("batch") in keep if r.get("batch")
                else r.get("session_id") not in batched)]


def _rows(table, client) -> list[dict]:
    return client.table(table).select("*").execute().data


def _boxes(cls: str, counts: Counter) -> str:
    return "".join(
        f'<label class="f"><input type="checkbox" class="{cls}" value="{_e(k)}">'
        f'{_e(k) or "—"}<span class="n">{n}</span></label>'
        for k, n in counts.most_common() if k
    )


def _attrs(r: dict, names: dict) -> str:
    return (f'data-who="{_e(names.get(r.get("engineer"), "unknown"))}" '
            f'data-tool="{_e(r.get("tool") or "")}" '
            f'data-proj="{_e(r.get("project") or "")}"')


def _diff_html(diff: str) -> str:
    """Colour a unified diff without pulling in a highlighter."""
    if not diff.strip():
        return '<div class="empty">No code changes recorded for this session.</div>'
    lines = []
    for line in diff.splitlines()[:2000]:
        cls = ("hd" if line.startswith(("diff ", "@@", "index ", "--- ", "+++ "))
               else "add" if line.startswith("+")
               else "del" if line.startswith("-") else "")
        lines.append(f'<span class="{cls}">{_e(line)}</span>' if cls else _e(line))
    return '<div class="diff">' + "\n".join(lines) + "</div>"


def _session_card(r: dict, names: dict) -> str:
    """One session: what was said, and what it changed, side by side."""
    turns = r.get("turns") or []
    asked = [t for t in turns if t.get("role") == "user"]
    title = (asked[0].get("text", "").strip().split("\n")[0][:90]
             if asked else "no prompt recorded")
    files = r.get("files") or []
    changed = (f'<span class="chip">{len(files)} file(s)</span>'
               f'<span class="chip">+{r.get("added", 0)} −{r.get("removed", 0)}</span>'
               if files else "")
    commits = (f'<span class="chip on">committed</span>' if r.get("commits") else "")
    return (
        f'<details class="card sess" {_attrs(r, names)}>'
        f'<summary><div class="rowhead">'
        f'<span class="chip">{_e(names.get(r.get("engineer"), "unknown"))}</span>'
        f'<b>{_e(r.get("tool") or "no tool")}</b>'
        f'<span class="chip">{_ago(r.get("started_at") or "")}</span>'
        f'{changed}{commits}</div>'
        f'<div class="said">{_e(title)}</div></summary>'
        f'<div class="subtabs">'
        f'<span class="subtab on" data-pane="talk">Conversation</span>'
        f'<span class="subtab" data-pane="code">What changed</span></div>'
        f'<div class="pane pane-talk">{_thread(r)}</div>'
        f'<div class="pane pane-code hide">'
        + (f'<div class="assumed">{_e(", ".join(files[:20]))}</div>' if files else "")
        + _diff_html(r.get("diff") or "")
        + '</div></details>')


def build(out_dir: Path) -> Path:
    from supabase import create_client

    c = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    engineers = _rows("engineers", c)
    names = {e["id"]: e.get("name") or e.get("email") for e in engineers}
    claims, corrections, asks = (_rows("claims", c), _rows("corrections", c),
                                 _rows("asks", c))
    try:
        sessions = _rows("chats", c)
    except Exception:
        sessions = []   # table not created yet — the rest of the page still builds
    # Only the newest extraction per session. Older batches stay in the store —
    # this is about what is currently true, not about deleting history.
    claims = _latest_batch(claims)
    corrections = _latest_batch(corrections)

    everything = claims + corrections + asks + sessions

    who_counts = Counter(names.get(r.get("engineer"), "unknown") for r in everything)
    tool_counts = Counter(r.get("tool") or "" for r in everything)
    proj_counts = Counter(r.get("project") or "" for r in everything)
    type_counts = Counter(r.get("type") or "" for r in claims)
    conf_counts = Counter(r.get("confidence") or "" for r in claims)

    # --- where people got stuck ---------------------------------------------
    by_tool = Counter(r.get("tool") or "" for r in corrections if r.get("tool"))
    top = by_tool.most_common(10)
    peak = max([n for _, n in top], default=1)
    bars = "".join(
        f'<div class="bar"><span class="lab">{_e(t)}</span>'
        f'<span class="track"><span class="fill" style="width:{n / peak * 100:.0f}%"></span></span>'
        f'<span class="n">{n}</span></div>' for t, n in top)

    stuck_cards = "".join(
        f'<div class="card" {_attrs(r, names)}>'
        f'<div class="rowhead"><b>{_e(r.get("tool") or "no tool")}</b>'
        f'<span class="chip">{_e(names.get(r.get("engineer"), "unknown"))}</span>'
        f'<span class="chip">{_e(r.get("corrected_on"))}</span></div>'
        f'<div class="assumed">assumed — {_e(r.get("agent_assumed"))}</div>'
        f'<div class="said">they said — <b>{_e(r.get("person_said"))}</b></div>'
        + (f'<div class="quote">{_e(r.get("evidence"))}</div>' if r.get("evidence") else "")
        + "</div>"
        for r in sorted(corrections, key=lambda r: r.get("corrected_on") or "", reverse=True))

    # --- what people asked for ----------------------------------------------
    ask_cards = "".join(
        f'<div class="card" {_attrs(r, names)}>'
        f'<div class="rowhead">'
        f'<span class="chip {"on" if r.get("deliberate") else ""}">'
        f'{"asked for" if r.get("deliberate") else "from a session"}</span>'
        f'<b>{_e(r.get("tool") or "no tool")}</b>'
        f'<span class="chip">{_e(names.get(r.get("engineer"), "unknown"))}</span>'
        f'<span class="chip">{_e(r.get("asked_on"))}</span></div>'
        f'<div class="said">{_e(r.get("ask"))}</div></div>'
        for r in sorted(asks, key=lambda r: (not r.get("deliberate"),
                                             r.get("asked_on") or ""), reverse=False))

    # --- what is known, grouped by tool -------------------------------------
    groups = {}
    for r in claims:
        groups.setdefault(r.get("tool") or "no tool", []).append(r)
    known = ""
    for tool, rows in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        cards = "".join(
            f'<div class="card" {_attrs(r, names)} data-type="{_e(r.get("type"))}" '
            f'data-conf="{_e(r.get("confidence"))}" data-gen="{1 if r.get("generalises") else 0}">'
            f'<div class="rowhead"><b>{_e(TYPE_LABELS.get(r.get("type"), r.get("type")))}</b>'
            f'<span class="chip">{_e(names.get(r.get("engineer"), "unknown"))}</span>'
            f'<span class="chip">{_e(r.get("confidence"))}</span>'
            + ('<span class="chip on">generalises</span>' if r.get("generalises") else "")
            + f'</div><div class="said">{_e(r.get("claim"))}</div>'
            + (f'<div class="assumed">why — {_e(r.get("why"))}</div>' if r.get("why") else "")
            + "</div>"
            for r in rows)
        known += (f'<div class="group"><h3 class="gtoggle">{_e(tool)} '
                  f'<span class="gcount">{len(rows)}</span></h3>{cards}</div>')

    session_cards = "".join(
        _session_card(r, names)
        for r in sorted(sessions, key=lambda r: r.get("started_at") or "", reverse=True))

    nav = "".join(
        f'<div class="nav" data-view="{v}" data-label="{lab}">{lab}'
        f'<span class="n">{n}</span></div>'
        for v, lab, n in (("sessions", "Sessions", len(sessions)),
                          ("stuck", "Where people got stuck", len(corrections)),
                          ("asks", "What people asked for", len(asks)),
                          ("knowledge", "What is known", len(claims))))

    def view(vid, body, empty):
        return (f'<div class="view hide" id="v-{vid}">{body}'
                f'<div class="empty">{empty}</div></div>')

    page = f"""<meta charset="utf-8">
<title>Harvest — everyone</title>
<style>{CSS}{EXTRA_CSS}</style>
<div class="app">
  <aside class="side">
    <div class="brand"><span class="dot">◆</span> Harvest</div>
    <div class="navlabel">Everyone</div>
    {nav}
  </aside>
  <main class="main">
    <div class="crumbs"><b>All engineers</b><span class="sep">/</span><span id="crumb"></span></div>
    <div class="body">
      {view("sessions", session_cards,
            "No sessions yet. They appear once someone has used a tool and signed in.")}
      {view("stuck", (f'<div style="margin-bottom:22px">{bars}</div>' if bars else "") + stuck_cards,
            "No corrections recorded yet. They appear once sessions have been summarised.")}
      {view("asks", ask_cards, "Nothing asked for yet.")}
      {view("knowledge", known, "No claims yet.")}
    </div>
  </main>
  <aside class="rail">
    <h4>Record</h4>
    <div class="stat"><span>People</span><b>{len(engineers)}</b></div>
    <div class="stat"><span>Claims</span><b>{len(claims)}</b></div>
    <div class="stat"><span>Corrections</span><b>{len(corrections)}</b></div>
    <div class="stat"><span>Requests</span><b>{len(asks)}</b></div>
    <h4>Person</h4>
    {_boxes("fwho", who_counts)}
    <h4>Tool</h4>
    {_boxes("ftool", tool_counts)}
    <h4>Project</h4>
    {_boxes("fproj", proj_counts)}
    <div id="rail-knowledge" class="hide">
      <h4>Type</h4>
      {"".join(f'<label class="f"><input type="checkbox" class="ftype" value="{_e(k)}">'
               f'{_e(TYPE_LABELS.get(k, k))}<span class="n">{n}</span></label>'
               for k, n in type_counts.most_common() if k)}
      <h4>Confidence</h4>
      {_boxes("fconf", conf_counts)}
      <h4>Scope</h4>
      <label class="f"><input type="checkbox" id="fgen">Only claims that generalise</label>
    </div>
  </aside>
</div>
<script>{JS}</script>"""

    path = out_dir / "admin.html"
    path.write_text(page, encoding="utf-8")
    return path
