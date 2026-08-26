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
import io
import keyword
import tokenize
from collections import Counter
from pathlib import Path

from .labels import TYPE_LABELS
from .page import CSS, _ago, _dur, _thread

EXTRA_CSS = """
.diff{font-family:var(--mono);font-size:12px;line-height:1.5;background:var(--bg);
      border:1px solid var(--line);border-radius:8px;padding:12px 14px;overflow-x:auto;
      max-height:460px;overflow-y:auto;white-space:pre}
.diff .add{color:var(--green)} .diff .del{color:var(--red)} .diff .hd{color:var(--blue)}
.filelist{border:1px solid var(--line);border-radius:8px;overflow:hidden;margin:0 0 18px}
.src{margin:0;border-bottom:1px solid var(--line)}
.src:last-child{border-bottom:none}
.src>summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:10px;
      padding:9px 14px;font-size:12.5px;color:var(--fg)}
.src>summary::-webkit-details-marker{display:none}
.src>summary:hover{background:rgba(255,255,255,.035)}
.src>summary:hover .nm{color:var(--blue)}
.src[open]>summary{background:rgba(255,255,255,.05);border-bottom:1px solid var(--line)}
.src .ico{flex:0 0 16px;opacity:.5}
.src .nm{font-family:var(--mono)}
.src .size{margin-left:auto;color:var(--muted);font-size:11.5px;font-family:var(--mono)}
.src .cut{color:var(--accent)}
.dir{border-bottom:1px solid var(--line)}
.dir:last-child{border-bottom:none}
.dir>summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:10px;
      padding:9px 14px;font-size:12.5px;color:var(--fg)}
.dir>summary::-webkit-details-marker{display:none}
.dir>summary:hover{background:rgba(255,255,255,.035)}
.dir>summary:hover .nm{color:var(--blue)}
.dir>summary .ico{color:var(--blue);opacity:.75}
.dir>summary .nm{font-family:var(--mono)}
.dir>summary .size{margin-left:auto;color:var(--muted);font-size:11.5px;
      font-family:var(--mono)}
.dir[open]>summary{background:rgba(255,255,255,.03)}
.dir .src:last-child{border-bottom:1px solid var(--line)}
.dir:last-child .src:last-child{border-bottom:none}
.src .diff{border:0;border-radius:0;max-height:520px;padding:10px 0;white-space:normal}
.ln{display:grid;grid-template-columns:52px 1fr}
.ln:hover{background:rgba(255,255,255,.03)}
.ln .n{color:var(--muted);opacity:.4;text-align:right;padding-right:16px;
      user-select:none;-webkit-user-select:none}
.ln .l{white-space:pre;padding-right:14px}
.code .kw{color:var(--blue)} .code .str{color:var(--green)}
.code .com{color:var(--muted);font-style:italic}
.code .num{color:var(--accent)} .code .fn{color:var(--fg);font-weight:600}
.meta{font-family:var(--mono);font-size:11.5px;color:var(--muted);margin:0 0 14px}
.meta b{color:var(--fg);font-weight:600}
.meta .row{padding:3px 0}
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


# PostgREST caps how many rows one response may carry, and it truncates
# silently — no error, nothing missing-looking. A page built from a truncated
# read is not smaller, it is WRONG: the tools people got stuck on most are
# ranked from whatever happened to arrive. So every table is read in pages.
PAGE = 1000

# A read that never ends means the server stopped honouring the range and is
# handing back the same rows. Better to say so than to fill memory quietly.
MAX_PAGES = 1000


def _rows(table, client) -> list[dict]:
    """Every row in the table, however many that is.

    Ordered by id so the window is stable between requests — without an order
    the server may return rows in any order and paging would both repeat and
    miss. Advances by what actually arrived rather than by PAGE, so a server
    configured with a smaller cap pages correctly instead of stopping early.
    """
    out: list[dict] = []
    start = 0
    for _ in range(MAX_PAGES):
        chunk = (client.table(table).select("*")
                 .order("id").range(start, start + PAGE - 1)
                 .execute().data)
        if not chunk:
            return out
        out.extend(chunk)
        start += len(chunk)
    raise RuntimeError(
        f"{table}: stopped after {MAX_PAGES} pages ({len(out)} rows). "
        "The store is not paging as expected — the page would be incomplete.")


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


# Python's own tokenizer, rather than a highlighter dependency or a pile of
# regexes. Regexes get f-strings, triple quotes and a `#` inside a string wrong,
# and being wrong about which half of a line is a comment is worse than plain
# black and white.
_KW_CLASS = {
    tokenize.COMMENT: "com",
    tokenize.STRING: "str",
    tokenize.NUMBER: "num",
}

# 3.12 stopped reporting f-strings as one STRING and started emitting the parts
# separately, so a map written against STRING alone leaves every f-string plain.
# getattr because the names do not exist on older interpreters.
for _n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
    if (_t := getattr(tokenize, _n, None)) is not None:
        _KW_CLASS[_t] = "str"


def _py_classes(text: str, lines: list[str]) -> list[list[str | None]]:
    """A class per character, or None. Empty on anything unparseable."""
    grid: list[list[str | None]] = [[None] * len(l) for l in lines]

    def paint(srow, scol, erow, ecol, cls):
        for row in range(srow, min(erow, len(grid) - 1) + 1):
            if row >= len(grid):
                break
            lo = scol if row == srow else 0
            hi = ecol if row == erow else len(grid[row])
            for col in range(lo, min(hi, len(grid[row]))):
                grid[row][col] = cls

    prev = ""
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            cls = _KW_CLASS.get(tok.type)
            if tok.type == tokenize.NAME:
                if keyword.iskeyword(tok.string):
                    cls = "kw"
                elif prev in ("def", "class"):
                    cls = "fn"
            if cls:
                paint(tok.start[0] - 1, tok.start[1], tok.end[0] - 1, tok.end[1], cls)
            if tok.type == tokenize.NAME:
                prev = tok.string
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        # A truncated or half-written file still deserves to be readable.
        pass
    return grid


def _code_html(path: str, text: str) -> str:
    """Source, coloured where we can be certain and plain where we cannot."""
    lines = text.split("\n")
    grid = _py_classes(text, lines) if path.endswith(".py") else None

    out = []
    for row, line in enumerate(lines):
        if grid is None:
            body = _e(line)
        else:
            marks = grid[row] if row < len(grid) else [None] * len(line)
            buf, start, cls = [], 0, marks[0] if marks else None
            for col in range(1, len(line) + 1):
                here = marks[col] if col < len(marks) else None
                if col == len(line) or here != cls:
                    chunk = _e(line[start:col])
                    buf.append(f'<span class="{cls}">{chunk}</span>' if cls else chunk)
                    start, cls = col, here
            body = "".join(buf)
        # A gutter, like every code viewer anyone already knows how to read.
        # Its own element rather than text, so selecting the code does not
        # drag the numbers along with it.
        out.append(f'<div class="ln"><span class="n">{row + 1}</span>'
                   f'<span class="l">{body or "&nbsp;"}</span></div>')
    return '<div class="diff code">' + "".join(out) + "</div>"


# Drawn rather than fetched: the page is one self-contained file, so an icon
# from anywhere else would simply not appear.
_ICON = ('<svg class="ico" width="16" height="16" viewBox="0 0 16 16" fill="none" '
         'stroke="currentColor" stroke-width="1.15" stroke-linejoin="round">'
         '<path d="M9.5 1.5H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5z"/>'
         '<path d="M9.5 1.5V5H13"/></svg>')


_FOLDER = ('<svg class="ico" width="16" height="16" viewBox="0 0 16 16" fill="none" '
           'stroke="currentColor" stroke-width="1.15" stroke-linejoin="round">'
           '<path d="M1.75 3.5h4l1.5 2h7a.75.75 0 0 1 .75.75v6.5a.75.75 0 0 1-.75.75'
           'H1.75a.75.75 0 0 1-.75-.75v-8.5a.75.75 0 0 1 .75-.75z"/></svg>')


def _tree(paths: list[str]) -> dict:
    """Nest a flat list of paths into folders."""
    root: dict = {}
    for path in paths:
        node = root
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = path          # a str leaf is a file
    return root


def _count(node: dict) -> int:
    return sum(1 if isinstance(v, str) else _count(v) for v in node.values())


def _squash(name: str, node: dict) -> tuple[str, dict]:
    """Fold a chain of single-child folders into one row.

    Three clicks to walk through `a/`, `b/`, `c/` when none of them held
    anything but the next one is three clicks that told you nothing.
    """
    while len(node) == 1:
        only = next(iter(node))
        if isinstance(node[only], str):
            break
        name, node = f"{name}/{only}", node[only]
    return name, node


def _tree_rows(node: dict, src: dict, depth: int = 0) -> str:
    pad = 14 + depth * 17
    dirs = {k: v for k, v in node.items() if isinstance(v, dict)}
    files = {k: v for k, v in node.items() if isinstance(v, str)}
    out = []

    # Folders first, then files — the order every file browser uses.
    for name in sorted(dirs):
        label, child = _squash(name, dirs[name])
        n = _count(child)
        out.append(
            f'<details class="dir"><summary style="padding-left:{pad}px">'
            f'{_FOLDER}<span class="nm">{_e(label)}</span>'
            f'<span class="size">{n} file{"s" if n != 1 else ""}</span></summary>'
            + _tree_rows(child, src, depth + 1) + '</details>')

    for name in sorted(files):
        path = files[name]
        f = src.get(path) or {}
        cut = ' <span class="cut">· truncated</span>' if f.get("truncated") else ""
        # Lines, not bytes. Nobody reads a file in bytes, and "212 lines" says
        # how big a thing you are about to pick up in a way "5052" never does.
        body = f.get("text") or ""
        n = body.count("\n") + 1 if body else 0
        out.append(f'<details class="src"><summary style="padding-left:{pad}px">{_ICON}'
                   f'<span class="nm">{_e(name)}</span>'
                   f'<span class="size">{n} lines{cut}</span></summary>'
                   + _code_html(path, body) + '</details>')
    return "".join(out)


def _sources_html(r: dict) -> str:
    """The code as it was left. This is the thing you can actually pick up."""
    src = r.get("sources") or {}
    if not src:
        return ('<div class="empty">No source kept for this session. Sessions '
                'captured before source snapshotting will be empty.</div>')
    return '<div class="filelist">' + _tree_rows(_tree(sorted(src)), src) + '</div>'


def _inputs_html(r: dict) -> str:
    """What it ran against — described, never copied."""
    rows = r.get("inputs") or []
    if not rows:
        return ""
    out = []
    for i in rows:
        shape = (i.get("shape") or {}).get("sheets") or {}
        where = "; ".join(
            f'{name}: {v.get("rows", "?")} rows — {", ".join(v.get("columns") or [])}'
            for name, v in shape.items()) or "shape not recorded"
        out.append(f'<div class="row"><b>{_e(i.get("name"))}</b> · '
                   f'{i.get("bytes", 0)} bytes · {_e(str(i.get("sha256", ""))[:12])}<br>'
                   f'{_e(where)}</div>')
    return '<div class="meta"><div class="row">Ran against:</div>' + "".join(out) + '</div>'


def _commits_html(r: dict) -> str:
    """Commits in full. A sha on its own points at a repo nobody else has."""
    log = r.get("commit_log") or []
    if not log:
        return ""
    out = "".join(
        f'<div class="row"><b>{_e(c.get("subject"))}</b><br>'
        f'{_e(str(c.get("sha", ""))[:10])} · {_e(c.get("author"))} · '
        f'{_e(str(c.get("date", ""))[:10])} · {len(c.get("files") or [])} file(s)</div>'
        for c in log)
    return '<div class="meta"><div class="row">Commits:</div>' + out + '</div>'


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
        f'<span class="subtab" data-pane="code">What changed</span>'
        f'<span class="subtab" data-pane="src">The code</span></div>'
        f'<div class="pane pane-talk">{_thread(r)}</div>'
        f'<div class="pane pane-code hide">'
        + (f'<div class="assumed">{_e(", ".join(files[:20]))}</div>' if files else "")
        + _commits_html(r)
        + _diff_html(r.get("diff") or "")
        + '</div>'
        f'<div class="pane pane-src hide">'
        + _inputs_html(r)
        + _sources_html(r)
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
