"""Render the harvested record as one self-contained dark HTML page."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

TYPE_LABELS = {
    "data_semantics": "What the data means",
    "hygiene_rule": "Data hygiene",
    "implicit_constraint": "Unmodelled constraints",
    "objective_tradeoff": "What good looks like",
    "acceptance_heuristic": "How they judge an answer",
    "exception_override": "Manual overrides",
    "vocabulary": "Vocabulary",
}

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0c0c0d; --panel:#141416; --raised:#1b1b1e; --line:#27272b;
  --fg:#e8e8ea; --muted:#8b8b93; --dim:#5f5f67;
  --accent:#d97757; --green:#4ade80; --red:#f87171; --blue:#7aa2f7;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;
}
body{background:var(--bg);color:var(--fg);font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;
     -webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.app{display:grid;grid-template-columns:248px minmax(0,1fr) 268px;min-height:100vh}
@media(max-width:1100px){.app{grid-template-columns:1fr}.side,.rail{display:none}}

.side{background:var(--panel);border-right:1px solid var(--line);padding:18px 12px;position:sticky;top:0;height:100vh;overflow-y:auto}
.brand{display:flex;align-items:center;gap:9px;padding:4px 10px 20px;font-weight:600;letter-spacing:-.01em}
.brand .dot{width:22px;height:22px;border-radius:6px;background:var(--accent);display:grid;place-items:center;font-size:12px}
.navlabel{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.07em;padding:16px 10px 7px}
.nav{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:7px;color:var(--muted);cursor:pointer;font-size:13.5px}
.nav:hover{background:var(--raised);color:var(--fg)}
.nav.on{background:var(--raised);color:var(--fg);font-weight:500}
.nav .n{margin-left:auto;color:var(--dim);font-size:12px;font-variant-numeric:tabular-nums}
.nav{line-height:1.4}

.main{min-width:0;padding:0 0 80px}
.crumbs{display:flex;align-items:center;gap:9px;padding:16px 32px;color:var(--muted);font-size:13px;
        border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:5}
.crumbs b{color:var(--fg);font-weight:500}
.crumbs .sep{color:var(--dim)}
.wrap{padding:30px 32px;max-width:900px}
h1{font-size:26px;line-height:1.25;letter-spacing:-.02em;font-weight:600;margin-bottom:12px}
h2{font-size:15px;font-weight:600;margin:30px 0 12px;letter-spacing:-.01em}

.meta{display:flex;flex-wrap:wrap;align-items:center;gap:8px;color:var(--muted);font-size:12.5px;margin-bottom:26px}
.meta .sep{color:var(--dim)}
.badge{font-family:var(--mono);font-size:11.5px;padding:3px 8px;border-radius:5px;
       background:rgba(217,119,87,.13);color:var(--accent);border:1px solid rgba(217,119,87,.3)}
.pos{color:var(--green)} .neg{color:var(--red)}

.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:15px 17px;margin-bottom:12px}
.card .claim{font-weight:500;margin-bottom:8px;letter-spacing:-.005em}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.tag{font-family:var(--mono);font-size:10.5px;padding:2px 7px;border-radius:4px;background:var(--raised);
     color:var(--muted);border:1px solid var(--line)}
.tag.stated{color:var(--green);border-color:rgba(74,222,128,.28)}
.tag.implied{color:var(--blue);border-color:rgba(122,162,247,.28)}
.tag.inferred{color:var(--muted)}
.tag.scoped{color:var(--accent);border-color:rgba(217,119,87,.28)}
.why{color:var(--muted);font-size:13px;margin-bottom:9px}
.why b{color:var(--fg);font-weight:500}
.quote{border-left:2px solid var(--line);padding:2px 0 2px 13px;color:var(--muted);font-size:13px;font-style:italic}

.bubble{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:10px}
.bubble .who{color:var(--dim);font-size:11.5px;font-family:var(--mono);margin-bottom:7px}
.empty{color:var(--muted);border:1px dashed var(--line);border-radius:10px;padding:26px;text-align:center}
.md h3{font-size:14px;margin:22px 0 9px;color:var(--fg)}
.md ul{margin:0 0 12px 20px} .md li{margin-bottom:7px}
.md blockquote{border-left:2px solid var(--line);padding-left:13px;color:var(--muted);font-style:italic;margin:7px 0 13px}
.md code{font-family:var(--mono);font-size:12.5px;background:var(--raised);padding:1.5px 5px;border-radius:4px}
.md p{margin-bottom:11px}
.md hr{border:0;border-top:1px solid var(--line);margin:24px 0}

.rail{border-left:1px solid var(--line);padding:22px 18px;position:sticky;top:0;height:100vh;overflow-y:auto}
.rail h4{font-size:12.5px;font-weight:600;margin:22px 0 10px}
.rail h4:first-child{margin-top:0}
.f{display:flex;align-items:center;gap:9px;padding:5px 0;color:var(--muted);font-size:13px;cursor:pointer}
.f:hover{color:var(--fg)}
.f input{accent-color:var(--accent);width:14px;height:14px;cursor:pointer}
.f .n{margin-left:auto;color:var(--dim);font-size:12px;font-variant-numeric:tabular-nums}
.stat{display:flex;justify-content:space-between;padding:6px 0;font-size:13px;color:var(--muted)}
.stat b{color:var(--fg);font-weight:600;font-variant-numeric:tabular-nums}
.hide{display:none}

/* conversation */
.thread{position:relative;padding-left:44px}
.thread:before{content:"";position:absolute;left:15px;top:8px;bottom:8px;width:1px;background:var(--line)}
.turn{position:relative;margin-bottom:14px}
.av{position:absolute;left:-44px;top:0;width:26px;height:26px;border-radius:50%;
    display:grid;place-items:center;font-size:11px;font-weight:600;background:var(--raised);
    border:1px solid var(--line);color:var(--muted)}
.av.user{background:#3b2a25;border-color:rgba(217,119,87,.4);color:var(--accent)}
.av.bot{background:#1e2a24;border-color:rgba(74,222,128,.3);color:var(--green)}
.msg{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px 16px}
.msg .body{white-space:pre-wrap;word-wrap:break-word}
.tmeta{color:var(--dim);font-size:12px;margin-top:8px}
.tmeta .sep{margin:0 6px}
.say{padding:2px 0 4px;white-space:pre-wrap;word-wrap:break-word}
details.steps{margin-bottom:14px}
details.steps>summary{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:11px 15px;color:var(--muted);font-size:13px;cursor:pointer;list-style:none;
    display:flex;align-items:center;gap:8px}
details.steps>summary::-webkit-details-marker{display:none}
details.steps>summary:after{content:"⌄";margin-left:auto;color:var(--dim)}
details.steps[open]>summary:after{content:"⌃"}
details.steps>summary:hover{border-color:#33333a}
.step{border-left:1px solid var(--line);margin:9px 0 0 14px;padding:7px 0 7px 14px}
.step code{font-family:var(--mono);font-size:12px;color:var(--fg);word-break:break-all}
.step .out{font-family:var(--mono);font-size:11.5px;color:var(--dim);white-space:pre-wrap;
    margin-top:6px;max-height:160px;overflow:auto}
.think{color:var(--dim);font-size:13px;font-style:italic;padding:2px 0 6px}
"""

JS = """
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
function show(view,id){
  $$('.view').forEach(v=>v.classList.add('hide'));
  const el=id?document.getElementById(id):$('#view-'+view);
  if(el) el.classList.remove('hide');
  $$('.nav').forEach(n=>n.classList.toggle('on', n.dataset.target===(id||('view-'+view))));
  $('#rail-filters').classList.toggle('hide', view!=='knowledge');
  $('#rail-convo').classList.toggle('hide', view!=='session');
  if(view==='session'&&el){
    let n={}; try{n=JSON.parse(el.dataset.counts||'{}')}catch(e){}
    $('#c-user').textContent=n.prompts||0;
    $('#c-assistant').textContent=n.responses||0;
    $('#c-steps').textContent=n.tools||0;
    turnFilter();
  }
  const c=$('#crumb'); if(c) c.textContent=el?el.dataset.title||'':'';
  window.scrollTo(0,0);
}
function turnFilter(){
  const on=$$('.fturn:checked').map(x=>x.value);
  ['t-user','t-assistant','t-steps'].forEach(k=>
    $$('.view:not(.hide) .'+k).forEach(e=>e.classList.toggle('hide',!on.includes(k))));
}
function expandAll(){
  $$('.view:not(.hide) details.steps').forEach(d=>d.open=$('#fexpand').checked);
}
function filter(){
  const types=$$('.ftype:checked').map(x=>x.value);
  const confs=$$('.fconf:checked').map(x=>x.value);
  const gen=$('#fgen').checked;
  let n=0;
  $$('#view-knowledge .card').forEach(c=>{
    const ok=types.includes(c.dataset.type)&&confs.includes(c.dataset.conf)
             &&(!gen||c.dataset.gen==='1');
    c.classList.toggle('hide',!ok); if(ok)n++;
  });
  $$('#view-knowledge .grp').forEach(g=>
    g.classList.toggle('hide', !g.querySelectorAll('.card:not(.hide)').length));
  $('#shown').textContent=n;
}
function init(){
  $$('.nav').forEach(n=>n.onclick=()=>show(n.dataset.view,n.dataset.target));
  $$('.ftype,.fconf,#fgen').forEach(i=>i.onchange=filter);
  $$('.fturn').forEach(i=>i.onchange=turnFilter);
  $('#fexpand').onchange=expandAll;
  show('knowledge');
}
// This script is inline at the end of the document, so DOMContentLoaded may
// already have fired — binding only on that event silently leaves the page dead.
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init);
else init();
"""


AGENT_LINE = re.compile(r"^(Codex|Claude Code|Cursor|Gemini|Copilot)\s*·\s*(.+)$")


def _md(text: str) -> str:
    """Enough markdown for what the reports contain."""
    out, in_ul = [], False
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("#"):
            lvl = len(s) - len(s.lstrip("#"))
            if in_ul: out.append("</ul>"); in_ul = False
            title = html.escape(s.lstrip("# "))
            out.append(f"<h1>{title}</h1>" if lvl == 1 else f"<h3>{title}</h3>")
            continue
        if s == "---":
            if in_ul: out.append("</ul>"); in_ul = False
            out.append("<hr>"); continue
        if s.startswith("> "):
            if in_ul: out.append("</ul>"); in_ul = False
            out.append(f"<blockquote>{_inline(s[2:])}</blockquote>"); continue
        if s.startswith("- "):
            if not in_ul: out.append("<ul>"); in_ul = True
            out.append(f"<li>{_inline(s[2:])}</li>"); continue
        if in_ul: out.append("</ul>"); in_ul = False
        if m := AGENT_LINE.match(s):
            bits = [b.strip() for b in m.group(2).split("·") if b.strip()]
            chips = "".join(f'<span class="sep">·</span><span>{html.escape(b)}</span>'
                            for b in bits)
            out.append(f'<div class="meta"><span class="badge">{m.group(1)}</span>{chips}</div>')
            continue
        if s: out.append(f"<p>{_inline(s)}</p>")
    if in_ul: out.append("</ul>")
    return "\n".join(out)


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", s)
    s = re.sub(r"(?<![A-Za-z0-9_])_([^_\n]+)_(?![A-Za-z0-9_])", r"<i>\1</i>", s)
    return s


def build(out_dir: Path) -> Path:
    from . import chats as chatstore

    claims = _jsonl(out_dir / "claims.jsonl")
    asks = _jsonl(out_dir / "asks.jsonl")

    # Summaries by session id, when one has been made. Chats exist regardless.
    summaries: dict[str, dict] = {}
    if (out_dir / "sessions").exists():
        for f in sorted((out_dir / "sessions").glob("*.md"), reverse=True):
            text = f.read_text(encoding="utf-8")
            m = re.search(r"session `([^`]+)`", text)
            title = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
            summaries[m.group(1) if m else f.stem] = {
                "title": (title.group(1) if title else f.stem).strip(), "body": text}

    sessions = []
    for c in chatstore.load_all(out_dir):
        sid = c.get("session_id") or c.get("checkpoint_id") or ""
        s = summaries.get(sid)
        first = next((t_["text"] for t_ in c.get("turns", []) if t_["role"] == "user"), "")
        sessions.append({
            "sid": sid, "chat": c,
            "title": (s or {}).get("title") or (first[:70] or "Untitled session"),
            "date": (c.get("started_at") or "")[:10],
            "summary": (s or {}).get("body"),
            "counts": chatstore.counts(c),
        })

    nav = ['<div class="nav" data-view="knowledge" data-target="view-knowledge">'
           f'Knowledge<span class="n">{len(claims)}</span></div>',
           '<div class="nav" data-view="asks" data-target="view-asks">'
           f'Asks<span class="n">{len(asks)}</span></div>',
           '<div class="navlabel">Sessions</div>']
    for i, s in enumerate(sessions):
        short = s["title"]
        if len(short) > 34:
            short = short[:33].rsplit(" ", 1)[0] + "…"
        mark = "" if s["summary"] else '<span class="n">·</span>'
        nav.append(f'<div class="nav" data-view="session" data-target="s{i}" '
                   f'title="{html.escape(s["title"])}">{html.escape(short)}{mark}</div>')

    views = [_knowledge_view(claims), _asks_view(asks)]
    for i, s in enumerate(sessions):
        c, n = s["chat"], s["counts"]
        tok = c.get("tokens") or {}
        added, removed = c.get("added", 0), c.get("removed", 0)
        chips = [f'<span class="badge">{html.escape(c.get("agent") or "Agent")}</span>']
        cp = c.get("checkpoints", 0)
        for bit in (c.get("model"), c.get("author"), _ago(c.get("started_at", "")),
                    _dur(c.get("duration_s", 0)),
                    f'{cp} checkpoint{"s" if cp != 1 else ""}' if cp else "",
                    f'{n["prompts"]} prompts',
                    f'{n["tools"]} tool calls',
                    f'{len(c.get("files", []))} file changes' if c.get("files") else "",
                    "committed" if c.get("commits") else "not committed"):
            if bit:
                chips.append(f'<span class="sep">·</span><span>{html.escape(str(bit))}</span>')
        if added or removed:
            chips.append('<span class="sep">·</span>'
                         f'<span class="pos">+{added}</span>'
                         f'<span class="sep" style="margin:0 3px">/</span>'
                         f'<span class="neg">−{removed}</span>')
        if tok.get("total"):
            chips.append(f'<span class="sep">·</span><span>{_tok(tok["total"])}</span>')
            if tok.get("api_calls"):
                chips.append('<span class="sep">·</span>'
                             f'<span>{tok["api_calls"]} API calls</span>')

        summary = (f'<h2>Summary</h2><div class="md">{_md(s["summary"])}</div>'
                   if s["summary"] else
                   '<h2>Summary</h2><div class="empty">Not summarised yet. Run '
                   '<code>harvest run</code> or <code>harvest weekly</code>.</div>')

        views.append(
            f'<div class="view hide" id="s{i}" data-title="{html.escape(s["title"])}" '
            f'data-counts=\'{json.dumps(n)}\'>'
            f'<div class="wrap"><h1>{html.escape(s["title"])}</h1>'
            f'<div class="meta">{"".join(chips)}</div>'
            f'{_thread(c)}<hr style="border:0;border-top:1px solid var(--line);margin:34px 0">'
            f'{summary}</div></div>')

    counts = {k: sum(1 for c in claims if c["type"] == k) for k in TYPE_LABELS}
    confs = {k: sum(1 for c in claims if c.get("confidence") == k)
             for k in ("stated", "implied", "inferred")}

    page = f"""<meta charset="utf-8">
<title>Harvest</title>
<style>{CSS}</style>
<div class="app">
  <aside class="side">
    <div class="brand"><span class="dot">◆</span> Harvest</div>
    {''.join(nav)}
  </aside>
  <main class="main">
    <div class="crumbs"><b>Cumulate</b><span class="sep">/</span><span id="crumb"></span></div>
    {''.join(views)}
  </main>
  <aside class="rail">
    <h4>Record</h4>
    <div class="stat"><span>Sessions</span><b>{len(sessions)}</b></div>
    <div class="stat"><span>Claims</span><b>{len(claims)}</b></div>
    <div class="stat"><span>Generalise</span><b>{sum(1 for c in claims if c.get('generalises'))}</b></div>
    <div class="stat"><span>Asks</span><b>{len(asks)}</b></div>
    <div id="rail-convo" class="hide">
      <h4>Filters</h4>
      <label class="f"><input type="checkbox" class="fturn" value="t-user" checked>Prompts<span class="n" id="c-user">0</span></label>
      <label class="f"><input type="checkbox" class="fturn" value="t-assistant" checked>Responses<span class="n" id="c-assistant">0</span></label>
      <label class="f"><input type="checkbox" class="fturn" value="t-steps" checked>Intermediate steps<span class="n" id="c-steps">0</span></label>
      <h4>View</h4>
      <label class="f"><input type="checkbox" id="fexpand">Expand all tool calls</label>
    </div>
    <div id="rail-filters">
      <h4>Type</h4>
      {''.join(f'<label class="f"><input type="checkbox" class="ftype" value="{k}" checked>'
               f'{v}<span class="n">{counts[k]}</span></label>'
               for k, v in TYPE_LABELS.items() if counts[k])}
      <h4>Confidence</h4>
      {''.join(f'<label class="f"><input type="checkbox" class="fconf" value="{k}" checked>'
               f'{k}<span class="n">{n}</span></label>' for k, n in confs.items() if n)}
      <h4>Scope</h4>
      <label class="f"><input type="checkbox" id="fgen">Only claims that generalise</label>
    </div>
  </aside>
</div>
<script>{JS}</script>"""

    path = out_dir / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


def _dur(sec: int) -> str:
    if not sec:
        return ""
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    return f"{sec // 3600}hr {(sec % 3600) // 60}min"


def _tok(n: int) -> str:
    if not n:
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M tokens"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K tokens"
    return f"{n} tokens"


def _ago(iso: str) -> str:
    return iso[:16].replace("T", " ") if iso else ""


def _thread(chat: dict) -> str:
    """Render turns the way the session actually happened."""
    turns = chat.get("turns", [])
    if not turns:
        return '<div class="empty">No transcript kept for this session.</div>'

    out, pending = [], []

    def flush():
        """Collapse the assistant/tool run that followed a prompt."""
        if not pending:
            return
        tools = [x for x in pending if x["role"] == "tool"]
        says = [x for x in pending if x["role"] == "assistant"]
        thinks = [x for x in pending if x["role"] == "reasoning"]
        if tools or thinks:
            inner = []
            for x in pending:
                if x["role"] == "tool":
                    label = "ran" if x.get("kind") == "exec" else "edited"
                    body = f'<code>{html.escape(x["text"][:400])}</code>'
                    if x.get("output"):
                        body += f'<div class="out">{html.escape(x["output"][:1200])}</div>'
                    inner.append(f'<div class="step t-tool"><b>{label}</b> {body}</div>')
                elif x["role"] == "reasoning" and x.get("text"):
                    inner.append(f'<div class="step t-reasoning think">'
                                 f'{html.escape(x["text"][:600])}</div>')
            out.append(
                f'<details class="steps t-steps"><summary>{len(says)} messages, '
                f'{len(tools)} tool calls</summary>{"".join(inner)}</details>')
        for x in says:
            out.append(f'<div class="turn t-assistant"><div class="av bot">◈</div>'
                       f'<div class="say">{_inline(x["text"])}</div></div>')
        pending.clear()

    for turn in turns:
        if turn["role"] == "user":
            flush()
            out.append(
                f'<div class="turn t-user"><div class="av user">U</div>'
                f'<div class="msg"><div class="body">{html.escape(turn["text"])}</div>'
                f'<div class="tmeta">{_ago(turn.get("ts",""))}</div></div></div>')
        else:
            pending.append(turn)
    flush()
    return f'<div class="thread">{"".join(out)}</div>'


def _jsonl(f: Path) -> list[dict]:
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def _knowledge_view(claims: list[dict]) -> str:
    if not claims:
        return ('<div class="view hide" id="view-knowledge" data-title="Knowledge">'
                '<div class="wrap"><h1>Knowledge</h1>'
                '<div class="empty">Nothing harvested yet.</div></div></div>')
    groups = []
    for kind, label in TYPE_LABELS.items():
        rows = [c for c in claims if c["type"] == kind]
        if not rows:
            continue
        cards = []
        for c in rows:
            gen = c.get("generalises")
            tags = f'<span class="tag {c.get("confidence","")}">{c.get("confidence","")}</span>'
            if not gen:
                tags += '<span class="tag scoped">this file only</span>'
            tags += f'<span class="tag">{html.escape(c.get("date",""))}</span>'
            why = (f'<div class="why"><b>Why:</b> {_inline(c["why"])}</div>'
                   if c.get("why") else "")
            cards.append(
                f'<div class="card" data-type="{kind}" data-conf="{c.get("confidence","")}"'
                f' data-gen="{1 if gen else 0}">'
                f'<div class="claim">{_inline(c["claim"])}</div>'
                f'<div class="tags">{tags}</div>{why}'
                f'<div class="quote">{_inline(c.get("evidence","").strip())}</div></div>')
        groups.append(f'<div class="grp"><h2>{label}</h2>{"".join(cards)}</div>')

    return ('<div class="view hide" id="view-knowledge" data-title="Knowledge">'
            '<div class="wrap"><h1>Knowledge</h1>'
            f'<div class="meta"><span id="shown">{len(claims)}</span>'
            f'<span>of {len(claims)} claims</span></div>'
            f'{"".join(groups)}</div></div>')


def _asks_view(asks: list[dict]) -> str:
    if not asks:
        return ('<div class="view hide" id="view-asks" data-title="Asks">'
                '<div class="wrap"><h1>Asks</h1>'
                '<div class="empty">Nothing recorded yet.</div></div></div>')
    items = []
    for a in reversed(asks):
        badge = ('<span class="badge">extracted</span>' if a.get("extracted")
                 else '<span class="tag">not extracted</span>')
        quotes = "".join(f'<div class="quote">{_inline(q)}</div>' for q in a.get("asks", []))
        files = (f'<div class="why">{html.escape(", ".join(a["files"][:8]))}</div>'
                 if a.get("files") else "")
        items.append(f'<div class="bubble"><div class="who">{html.escape(a.get("date",""))}'
                     f' · {a.get("words",0)} words</div>{quotes}'
                     f'<div class="tags" style="margin-top:10px">{badge}</div>{files}</div>')
    return ('<div class="view hide" id="view-asks" data-title="Asks">'
            '<div class="wrap"><h1>What people asked for</h1>'
            '<div class="meta">Every real request, extracted or not.</div>'
            f'{"".join(items)}</div></div>')
