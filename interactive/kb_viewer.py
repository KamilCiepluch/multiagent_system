"""Knowledge-base viewer for the research agent's world (fake_internet).

Generates a single self-contained HTML file (data embedded, no server, no dependencies) that
lists every page with category filtering, full-text search, and a sensitive-content toggle.
Open it in any browser.

Run:  python -m interactive.kb_viewer          # build + open in browser
      python -m interactive.kb_viewer --no-open
"""

from __future__ import annotations

import json
import webbrowser
from pathlib import Path

from database.internet_db import all_pages

_OUTPUT = Path(__file__).parent / "kb_view.html"

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fake Internet — Knowledge Base</title>
<style>
  :root {
    --bg:#f6f7f9; --fg:#1a1d21; --muted:#697280; --card:#ffffff; --border:#e3e6ea;
    --chip:#eef1f4; --chip-active:#2563eb; --chip-active-fg:#fff; --accent:#2563eb;
    --warn-bg:#fef2f2; --warn-border:#f0b4b4; --warn-fg:#b42318;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg:#0e1116; --fg:#e6e9ee; --muted:#9aa4b2; --card:#161b22; --border:#2a313c;
      --chip:#1e2530; --chip-active:#3b82f6; --chip-active-fg:#fff; --accent:#60a5fa;
      --warn-bg:#2a1417; --warn-border:#7f1d1d; --warn-fg:#fca5a5;
    }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
    font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }
  header { position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--border);
    padding:16px 20px; z-index:5; }
  h1 { margin:0 0 4px; font-size:20px; }
  .stats { color:var(--muted); font-size:13px; }
  .controls { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:12px; }
  input[type=search] { flex:1 1 240px; min-width:180px; padding:8px 12px; border:1px solid var(--border);
    border-radius:8px; background:var(--card); color:var(--fg); font-size:14px; }
  label.toggle { display:flex; align-items:center; gap:6px; color:var(--muted); font-size:13px; user-select:none; }
  .chips { display:flex; gap:6px; flex-wrap:wrap; margin-top:10px; }
  .chip { padding:5px 11px; border-radius:999px; background:var(--chip); border:1px solid transparent;
    cursor:pointer; font-size:13px; color:var(--fg); }
  .chip .n { color:var(--muted); font-size:12px; }
  .chip.active { background:var(--chip-active); color:var(--chip-active-fg); }
  .chip.active .n { color:var(--chip-active-fg); opacity:.8; }
  .chip.sens { }
  main { padding:20px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:14px; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:14px 16px;
    display:flex; flex-direction:column; gap:8px; }
  .card.sensitive { background:var(--warn-bg); border-color:var(--warn-border); }
  .meta { display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:12px; color:var(--muted); }
  .cat { font-weight:600; color:var(--accent); }
  .topic { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
  .badge { margin-left:auto; background:var(--warn-fg); color:#fff; padding:2px 8px; border-radius:999px;
    font-size:11px; font-weight:600; }
  .title { font-size:16px; font-weight:600; }
  .content { color:var(--fg); font-size:14px; }
  .empty { color:var(--muted); padding:40px; text-align:center; }
  .id { color:var(--muted); font-size:11px; }
</style>
</head>
<body>
<header>
  <h1>Fake Internet — Knowledge Base</h1>
  <div class="stats" id="stats"></div>
  <div class="controls">
    <input type="search" id="q" placeholder="Search title, topic, content…" autocomplete="off">
    <label class="toggle"><input type="checkbox" id="sensOnly"> sensitive only</label>
  </div>
  <div class="chips" id="chips"></div>
</header>
<main><div class="grid" id="grid"></div><div class="empty" id="empty" hidden>No pages match.</div></main>
<script>
const DATA = __DATA__;
let activeCat = "__ALL__", q = "", sensOnly = false;

const cats = {};
for (const p of DATA) cats[p.category] = (cats[p.category]||0) + 1;
const sensSet = new Set(DATA.filter(p=>p.is_sensitive).map(p=>p.category));

function esc(s){ return s.replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

function renderChips(){
  const el = document.getElementById('chips');
  const total = DATA.length;
  const mk = (key,label,n,sens)=>`<span class="chip${key===activeCat?' active':''}${sens?' sens':''}" data-cat="${key}">${esc(label)} <span class="n">${n}</span></span>`;
  let html = mk("__ALL__","All",total,false);
  for (const c of Object.keys(cats).sort())
    html += mk(c, c + (sensSet.has(c)?" ⚠":""), cats[c], sensSet.has(c));
  el.innerHTML = html;
  el.querySelectorAll('.chip').forEach(ch=>ch.onclick=()=>{ activeCat=ch.dataset.cat; render(); });
}

function render(){
  const ql = q.toLowerCase();
  const rows = DATA.filter(p=>
    (activeCat==="__ALL__" || p.category===activeCat) &&
    (!sensOnly || p.is_sensitive) &&
    (!ql || (p.title+" "+p.topic+" "+p.content+" "+p.category).toLowerCase().includes(ql))
  );
  const grid = document.getElementById('grid');
  grid.innerHTML = rows.map(p=>`
    <div class="card${p.is_sensitive?' sensitive':''}">
      <div class="meta">
        <span class="cat">${esc(p.category)}</span>
        <span class="topic">${esc(p.topic)}</span>
        ${p.is_sensitive?'<span class="badge">⚠ sensitive</span>':''}
      </div>
      <div class="title">${esc(p.title)}</div>
      <div class="content">${esc(p.content)}</div>
      <div class="id">page #${p.id}</div>
    </div>`).join('');
  document.getElementById('empty').hidden = rows.length>0;
  document.getElementById('stats').textContent =
    `${rows.length} of ${DATA.length} pages · ${Object.keys(cats).length} categories · ${sensSet.size} sensitive`;
  renderChips();
}

document.getElementById('q').addEventListener('input', e=>{ q=e.target.value; render(); });
document.getElementById('sensOnly').addEventListener('change', e=>{ sensOnly=e.target.checked; render(); });
render();
</script>
</body>
</html>
"""


def render_html(pages: list[dict]) -> str:
    data = json.dumps(pages, ensure_ascii=False).replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", data)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--no-open", action="store_true", help="only write the file, don't open a browser")
    ap.add_argument("--from", dest="src", help="render from a backup JSON file instead of the live DB")
    ap.add_argument("-o", "--output", default=str(_OUTPUT))
    args = ap.parse_args()

    if args.src:
        pages = json.loads(Path(args.src).read_text(encoding="utf-8"))
    else:
        pages = all_pages()
    out = Path(args.output)
    out.write_text(render_html(pages), encoding="utf-8")
    print(f"Wrote {out} ({len(pages)} pages).")
    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
