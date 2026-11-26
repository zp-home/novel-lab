#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_pages.py —— 构建 GitHub Pages 静态部署产物

默认输出到 `.gh-pages-tmp/`（已在 .gitignore 中忽略），包含：
  - index.html        静态站点首页导航
  - dashboard.html    四界 · 长篇小说 Agent 记忆大屏
  - progress.html     四界 · 正文生成进度看板（内联最新快照 + progress.json）
  - outline.html      四界 · 5000 章四层大纲浏览器（6 幕 / 100 卷 / 500 弧 / 前 200 章节拍）
  - console/          novel-lab Web 控制台只读静态版（含 sijie 与 demo_web 快照）
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

import outline as OL
import progress as PR


def _safe_json_for_html(obj: object) -> str:
    """避免 JSON 内出现 `</script>` 提前闭合 HTML script 标签。"""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def build_progress(site: Path, book: OL.Book) -> dict:
    chapters_dir = ROOT / "out" / "sijie" / "chapters"
    if not chapters_dir.exists() or not list(chapters_dir.glob("*.txt")):
        chapters_dir = ROOT / "out" / "books"
    snap = PR.snapshot(chapters_dir, book, 200)
    (site / "progress.json").write_text(
        json.dumps(snap, ensure_ascii=False), encoding="utf-8"
    )

    tpl = (ROOT / "out" / "progress_inline.html").read_text(encoding="utf-8")
    data_line = f"let DATA = {_safe_json_for_html(snap)};"
    html = re.sub(r"^let DATA = .*;$", lambda _: data_line, tpl, count=1, flags=re.M)
    html = html.replace("每章约 4000 字", "目标每章 3600 字")
    (site / "progress.html").write_text(html, encoding="utf-8")
    return snap


def build_outline_page(site: Path, outline_path: Path) -> dict:
    raw = json.loads(outline_path.read_text(encoding="utf-8"))
    compact_vols = []
    for v in raw["volumes"]:
        arcs_out = []
        for ar in v["arcs"]:
            item = {
                "no": ar["no"],
                "name": ar["name"],
                "start": ar["start"],
                "end": ar["end"],
                "goal": ar["goal"],
                "escalates": ar["escalates"],
            }
            if v["no"] <= 4:
                item["chapters"] = [
                    {
                        "no": c["no"],
                        "title": c["title"],
                        "goal": c.get("goal", ""),
                        "ends_with": c.get("ends_with", ""),
                        "beats": [
                            {"kind": b.get("kind", ""), "spec": b.get("spec") or b.get("text", "")}
                            for b in c.get("beats", [])
                        ],
                    }
                    for c in ar.get("chapters", [])
                ]
            arcs_out.append(item)
        compact_vols.append({
            "no": v["no"],
            "act": v["act"],
            "name": v["name"],
            "start": v["start"],
            "end": v["end"],
            "goal": v["goal"],
            "escalates": v["escalates"],
            "arcs": arcs_out,
        })

    payload = {
        "title": raw["title"],
        "logline": raw["logline"],
        "spine": raw["spine"],
        "acts": raw["acts"],
        "milestones": raw["milestones"],
        "volumes": compact_vols,
    }

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>四界 · 5000 章四层大纲浏览器</title>
<style>
:root{{
  --bg:#080b12;--panel:#111827;--panel2:#151d2e;--line:#1e293b;
  --txt:#cbd5e1;--txt2:#94a3b8;--dim:#64748b;
  --cyan:#22d3ee;--emerald:#34d399;--amber:#fbbf24;--rose:#fb7185;--violet:#a78bfa;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--txt);font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;font-size:13.5px;line-height:1.65}}
a{{color:var(--cyan);text-decoration:none}}
a:hover{{text-decoration:underline}}
.wrap{{max-width:1360px;margin:0 auto;padding:22px 24px 72px}}
header{{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;padding-bottom:16px;border-bottom:1px solid var(--line);margin-bottom:18px}}
h1{{font-size:21px;color:#f1f5f9}}
h1 span{{color:var(--cyan)}}
.nav{{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px}}
.card{{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:14px}}
.card h2{{font-size:14px;color:#f1f5f9;margin-bottom:10px;display:flex;align-items:center;gap:8px}}
.tag{{font-size:10.5px;padding:2px 7px;border-radius:4px;background:rgba(34,211,238,.12);color:var(--cyan)}}
.spine-box{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}}
.kv{{background:rgba(15,23,42,.65);border:1px solid var(--line);border-radius:8px;padding:12px}}
.kv .k{{font-size:11px;color:var(--dim);margin-bottom:4px}}
.kv .v{{color:#e2e8f0}}
.acts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:10px}}
.act{{background:rgba(15,23,42,.65);border:1px solid var(--line);border-radius:8px;padding:12px;cursor:pointer;transition:border-color .15s}}
.act:hover,.act.active{{border-color:var(--cyan)}}
.act-head{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;font-weight:600;color:#f1f5f9}}
.act-range{{font-size:11px;color:var(--cyan);font-family:ui-monospace,monospace}}
.act-row{{font-size:12px;color:var(--txt2);margin-top:4px}}
.act-row b{{color:#cbd5e1;font-weight:500}}
.controls{{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}}
.input,.select{{background:#0f172a;color:#e2e8f0;border:1px solid var(--line);border-radius:6px;padding:7px 10px;font-size:13px}}
.input{{min-width:240px;flex:1}}
.btn{{background:rgba(34,211,238,.12);color:var(--cyan);border:1px solid rgba(34,211,238,.3);border-radius:6px;padding:6px 11px;cursor:pointer;font-size:12px}}
.btn:hover{{background:rgba(34,211,238,.22)}}
.ms-list{{display:flex;flex-wrap:wrap;gap:8px}}
.ms-chip{{background:rgba(15,23,42,.75);border:1px solid var(--line);border-radius:6px;padding:5px 9px;font-size:12px}}
.ms-chip .ch{{color:var(--cyan);font-family:ui-monospace,monospace;margin-right:5px}}
.ms-chip .who{{color:var(--amber);margin-right:4px}}
.vol{{border:1px solid var(--line);border-radius:8px;margin-bottom:8px;background:rgba(15,23,42,.55);overflow:hidden}}
.vol-head{{padding:10px 14px;display:flex;justify-content:space-between;align-items:center;gap:12px;cursor:pointer;flex-wrap:wrap}}
.vol-head:hover{{background:rgba(30,41,59,.45)}}
.vol-title{{font-weight:600;color:#f1f5f9}}
.vol-meta{{font-size:12px;color:var(--txt2)}}
.vol-body{{padding:0 14px 12px;border-top:1px solid var(--line);display:none}}
.vol.open .vol-body{{display:block}}
.arc{{margin-top:10px;padding:10px;border:1px solid var(--line);border-radius:6px;background:rgba(8,11,18,.55)}}
.arc-head{{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}}
.arc-name{{color:var(--emerald);font-weight:600}}
.ch-list{{margin-top:8px;display:grid;gap:6px}}
.ch-item{{border:1px solid var(--line);border-radius:6px;padding:8px 10px;background:rgba(17,24,39,.75)}}
.ch-title{{font-weight:600;color:#e2e8f0;margin-bottom:3px}}
.ch-goal{{font-size:12px;color:var(--txt2);margin-bottom:4px}}
.beats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:6px;margin-top:6px}}
.beat{{font-size:11.5px;background:rgba(15,23,42,.85);border:1px solid var(--line);border-radius:5px;padding:5px 8px;color:var(--txt2)}}
.beat .kind{{color:var(--violet);font-weight:600;margin-right:4px}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>《<span>四界</span>》四层大纲浏览器</h1>
      <div style="font-size:12px;color:var(--dim);margin-top:3px">6 幕 · 100 卷 · 500 弧 · 5000 章骨架（含第 1～200 章完整章纲与 4 节拍）</div>
    </div>
    <nav class="nav">
      <a href="index.html">首页导航</a>
      <a href="dashboard.html">记忆大屏</a>
      <a href="progress.html">生成进度</a>
      <a href="console/">Web 控制台</a>
    </nav>
  </header>

  <section class="card">
    <h2>总纲与故事主脊 <span class="tag">Core Spine</span></h2>
    <div class="spine-box" id="spineBox"></div>
  </section>

  <section class="card">
    <h2>六幕结构 <span class="tag">点击任意一幕可筛选下方卷纲</span></h2>
    <div class="acts" id="actsBox"></div>
  </section>

  <section class="card">
    <h2>关键人物与主线里程碑 <span class="tag" id="msCount"></span></h2>
    <div class="controls">
      <select id="whoFilter" class="select"><option value="">全部主要事件</option><option value="__all__">含全书 108 阶升级（125 条）</option></select>
    </div>
    <div class="ms-list" id="msBox"></div>
  </section>

  <section class="card">
    <h2>卷纲 / 弧纲 / 前 200 章章纲 <span class="tag" id="volCount"></span></h2>
    <div class="controls">
      <select id="actFilter" class="select"><option value="">全部 6 幕（100 卷）</option></select>
      <input id="kwInput" class="input" type="search" placeholder="搜索卷名、物件、章名或节拍（如：铜镜、账本、沈鹤年、第12章）">
      <button id="btnCh200" class="btn" type="button">只看前 200 章（1～4 卷）</button>
      <button id="btnReset" class="btn" type="button">重置</button>
    </div>
    <div id="volsBox"></div>
  </section>
</div>
<script>
const OUTLINE = {_safe_json_for_html(payload)};
let selectedAct = "";
let onlyFirst4 = false;

function esc(s){{return String(s||"").replace(/[&<>"]/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]));}}

function renderTop(){{
  document.getElementById("spineBox").innerHTML = `
    <div class="kv"><div class="k">一句话故事</div><div class="v">${{esc(OUTLINE.logline)}}</div></div>
    <div class="kv"><div class="k">核心主脊</div><div class="v">${{esc(OUTLINE.spine)}}</div></div>
  `;
  const actsBox = document.getElementById("actsBox");
  const actSel = document.getElementById("actFilter");
  actsBox.innerHTML = OUTLINE.acts.map(a => `
    <div class="act" data-act="${{a.no}}">
      <div class="act-head"><span>${{esc(a.name)}}</span><span class="act-range">ch ${{a.start}}~${{a.end}}</span></div>
      <div class="act-row"><b>冲突：</b>${{esc(a.conflict)}}</div>
      <div class="act-row"><b>不可逆：</b>${{esc(a.irreversible)}}</div>
      <div class="act-row"><b>升级：</b>${{esc(a.escalates)}}</div>
    </div>
  `).join("");
  OUTLINE.acts.forEach(a => {{
    const opt = document.createElement("option");
    opt.value = String(a.no);
    opt.textContent = `${{a.name}} (ch ${{a.start}}~${{a.end}})`;
    actSel.appendChild(opt);
  }});
  actsBox.querySelectorAll(".act").forEach(el => {{
    el.addEventListener("click", () => {{
      const no = el.dataset.act;
      selectedAct = selectedAct === no ? "" : no;
      onlyFirst4 = false;
      actSel.value = selectedAct;
      actsBox.querySelectorAll(".act").forEach(x => x.classList.toggle("active", x.dataset.act === selectedAct));
      renderVolumes();
    }});
  }});
}}

function renderMilestones(){{
  const mode = document.getElementById("whoFilter").value;
  const list = OUTLINE.milestones.filter(m => {{
    if (mode === "__all__") return true;
    return m.who !== "林昭" || /飞升|身死|杀|对决|废|隐居|登场|叛/.test(m.event);
  }});
  document.getElementById("msCount").textContent = `${{list.length}} 条`;
  document.getElementById("msBox").innerHTML = list.map(m =>
    `<div class="ms-chip"><span class="ch">ch${{m.chapter}}</span><span class="who">${{esc(m.who)}}</span><span>(Lv.${{m.level}}) ${{esc(m.event)}}</span></div>`
  ).join("");
}}

function renderVolumes(){{
  const kw = document.getElementById("kwInput").value.trim().toLowerCase();
  const vols = OUTLINE.volumes.filter(v => {{
    if (onlyFirst4 && v.no > 4) return false;
    if (selectedAct && String(v.act) !== selectedAct) return false;
    if (!kw) return true;
    const hay = [
      v.name, v.goal, v.escalates, `第${{v.no}}卷`,
      ...v.arcs.map(a => `${{a.name}} ${{a.goal}} ${{a.escalates}} ` + (a.chapters||[]).map(c => `第${{c.no}}章 ${{c.title}} ${{c.goal}} ${{c.ends_with}} ` + c.beats.map(b=>b.spec).join(" ")).join(" "))
    ].join(" ").toLowerCase();
    return hay.includes(kw);
  }});
  document.getElementById("volCount").textContent = `显示 ${{vols.length}} / ${{OUTLINE.volumes.length}} 卷`;
  const box = document.getElementById("volsBox");
  box.innerHTML = vols.map((v, idx) => {{
    const open = (idx === 0 || (onlyFirst4 && v.no === 1) || kw) ? "open" : "";
    const arcsHtml = v.arcs.map(ar => {{
      const chHtml = ar.chapters ? `<div class="ch-list">` + ar.chapters.map(c => `
        <div class="ch-item">
          <div class="ch-title">第 ${{c.no}} 章《${{esc(c.title)}}》</div>
          <div class="ch-goal">目标：${{esc(c.goal)}}</div>
          <div class="ch-goal">收束：${{esc(c.ends_with)}}</div>
          <div class="beats">${{c.beats.map((b,i)=>`<div class="beat"><span class="kind">${{i+1}}. [${{esc(b.kind)}}]</span>${{esc(b.spec)}}</div>`).join("")}}</div>
        </div>`).join("") + `</div>` : `<div style="font-size:12px;color:var(--dim);margin-top:4px">（第 5～100 卷为卷/弧骨架视图；完整 5000 章 JSON 可由 src/outline.py 生成）</div>`;
      return `<div class="arc">
        <div class="arc-head"><span class="arc-name">弧 ${{ar.no}} · ${{esc(ar.name)}}</span><span class="act-range">ch ${{ar.start}}~${{ar.end}} · ${{esc(ar.escalates)}}</span></div>
        <div style="font-size:12.5px;color:var(--txt2);margin-top:4px">${{esc(ar.goal)}}</div>
        ${{chHtml}}
      </div>`;
    }}).join("");
    return `<div class="vol ${{open}}">
      <div class="vol-head" onclick="this.parentElement.classList.toggle('open')">
        <span class="vol-title">${{esc(v.name)}}</span>
        <span class="vol-meta">ch ${{v.start}}~${{v.end}} · ${{v.arcs.length}} 弧 · 点击展开</span>
      </div>
      <div class="vol-body">
        <div style="font-size:12.5px;color:var(--txt2);margin-top:10px"><b>本卷目标：</b>${{esc(v.goal)}}</div>
        ${{arcsHtml}}
      </div>
    </div>`;
  }}).join("");
}}

renderTop();
renderMilestones();
renderVolumes();
document.getElementById("whoFilter").addEventListener("change", renderMilestones);
document.getElementById("actFilter").addEventListener("change", e => {{ selectedAct = e.target.value; onlyFirst4 = false; renderVolumes(); }});
document.getElementById("kwInput").addEventListener("input", renderVolumes);
document.getElementById("btnCh200").addEventListener("click", () => {{ onlyFirst4 = true; selectedAct = ""; document.getElementById("actFilter").value = ""; renderVolumes(); }});
document.getElementById("btnReset").addEventListener("click", () => {{ onlyFirst4 = false; selectedAct = ""; document.getElementById("actFilter").value = ""; document.getElementById("kwInput").value = ""; renderVolumes(); }});
</script>
</body>
</html>"""
    (site / "outline.html").write_text(html, encoding="utf-8")
    return {"acts": len(raw["acts"]), "volumes": len(raw["volumes"]), "milestones": len(raw["milestones"])}


def build_console(site: Path) -> dict:
    console_dir = site / "console"
    data_dir = console_dir / "data"
    if console_dir.exists():
        shutil.rmtree(console_dir)
    shutil.copytree(ROOT / "web" / "static", console_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    projects = []
    # sijie
    sijie_manifest_p = ROOT / "out" / "sijie" / "manifest.json"
    sijie_manifest = {}
    if sijie_manifest_p.exists():
        sijie_manifest = json.loads(sijie_manifest_p.read_text(encoding="utf-8"))
        sijie_manifest["running"] = None
    projects.append({
        "name": "sijie",
        "title": "四界",
        "genre": "仙侠",
        "chapters": 5000,
        "words_per_chapter": 3600,
        "style": "webnovel",
        "model": "auto/deepseek-v4.1-flash-max",
        "written": sijie_manifest.get("written", 0),
        "total": sijie_manifest.get("total", 5000),
        "logline": "青牛镇打铁的少年，在母亲留下的一面铜镜里发现半道碑印，为了弄清母亲当年为什么把镜子同时押给两家，一步步走进四界的旧账里。",
        "running": False,
    })
    (data_dir / "manifest_sijie.json").write_text(
        json.dumps(sijie_manifest, ensure_ascii=False), encoding="utf-8"
    )

    sijie_ch_dir = data_dir / "chapters" / "sijie"
    sijie_ch_dir.mkdir(parents=True, exist_ok=True)
    src_ch_dir = ROOT / "out" / "sijie" / "chapters"
    ch_count = 0
    if src_ch_dir.exists():
        for f in sorted(src_ch_dir.glob("*.txt")):
            if f.stem.isdigit() and f.stat().st_size > 500:
                no = int(f.stem)
                (sijie_ch_dir / f"{no}.json").write_text(
                    json.dumps({"no": no, "text": f.read_text(encoding="utf-8")}, ensure_ascii=False),
                    encoding="utf-8",
                )
                ch_count += 1

    log_p = ROOT / "out" / "sijie" / "run.log"
    lines = log_p.read_text(encoding="utf-8", errors="replace").splitlines()[-200:] if log_p.exists() else []
    (data_dir / "logs_sijie.json").write_text(
        json.dumps({"lines": lines}, ensure_ascii=False), encoding="utf-8"
    )

    # demo_web
    demo_manifest_p = ROOT / "out" / "demo_web" / "manifest.json"
    if demo_manifest_p.exists():
        dm = json.loads(demo_manifest_p.read_text(encoding="utf-8"))
        dm["running"] = None
        (data_dir / "manifest_demo_web.json").write_text(
            json.dumps(dm, ensure_ascii=False), encoding="utf-8"
        )
        demo_ch_dir = data_dir / "chapters" / "demo_web"
        demo_ch_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted((ROOT / "out" / "demo_web" / "chapters").glob("*.txt")):
            if f.stem.isdigit():
                no = int(f.stem)
                (demo_ch_dir / f"{no}.json").write_text(
                    json.dumps({"no": no, "text": f.read_text(encoding="utf-8")}, ensure_ascii=False),
                    encoding="utf-8",
                )

    (data_dir / "projects.json").write_text(
        json.dumps({"projects": projects}, ensure_ascii=False), encoding="utf-8"
    )

    shim = """/* GitHub Pages 只读静态适配层：把 /api/* 映射到 ./data/* 快照 */
(function () {
  const realFetch = window.fetch.bind(window);
  function jsonResp(obj, status) {
    return new Response(JSON.stringify(obj), {
      status: status || 200,
      headers: { 'Content-Type': 'application/json; charset=utf-8' }
    });
  }
  window.fetch = async function (input, init) {
    const raw = typeof input === 'string' ? input : (input && input.url) || '';
    const url = raw.split('?')[0];
    if (url === '/api/projects') {
      return realFetch('./data/projects.json');
    }
    const mMan = url.match(/^\\/api\\/manifest\\/([^/]+)$/);
    if (mMan) {
      return realFetch('./data/manifest_' + decodeURIComponent(mMan[1]) + '.json');
    }
    const mCh = url.match(/^\\/api\\/chapter\\/([^/]+)\\/(\\d+)$/);
    if (mCh) {
      const r = await realFetch('./data/chapters/' + decodeURIComponent(mCh[1]) + '/' + mCh[2] + '.json');
      if (!r.ok) return jsonResp({ error: '该章尚未生成（静态快照模式）' }, 404);
      return r;
    }
    const mLog = url.match(/^\\/api\\/log\\/([^/]+)$/);
    if (mLog) {
      const r = await realFetch('./data/logs_' + decodeURIComponent(mLog[1]) + '.json');
      if (!r.ok) return jsonResp({ lines: [] }, 200);
      return r;
    }
    if (url === '/api/run' || url === '/api/stop') {
      return jsonResp({ error: '当前为 GitHub Pages 只读静态展示版，启停任务请在本地运行 python web/server.py' }, 400);
    }
    return realFetch(input, init);
  };
})();
"""
    (console_dir / "static-shim.js").write_text(shim, encoding="utf-8")

    idx = (console_dir / "index.html").read_text(encoding="utf-8")
    idx = idx.replace(
        '<script src="app.js"></script>',
        '<script src="static-shim.js"></script>\n<script src="app.js"></script>',
    )
    idx = idx.replace(
        "<p>确定性大纲 · 逐章正文 · 文体质量</p>",
        "<p>确定性大纲 · 逐章正文 · 文体质量（静态快照只读版 · <a href=\"../\" style=\"color:#5aa2ff\">返回首页</a>）</p>",
    )
    (console_dir / "index.html").write_text(idx, encoding="utf-8")
    return {"projects": len(projects), "sijie_chapters": ch_count}


def build_index(site: Path, snap: dict, ol_info: dict, con_info: dict) -> None:
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>novel-lab · 5000 章小说 Agent 静态展示站</title>
<style>
:root{{
  --bg:#080b12;--panel:#111827;--panel2:#151d2e;--line:#1e293b;
  --txt:#cbd5e1;--txt2:#94a3b8;--dim:#64748b;
  --cyan:#22d3ee;--emerald:#34d399;--amber:#fbbf24;--violet:#a78bfa;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--txt);font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;line-height:1.65}}
.wrap{{max-width:1120px;margin:0 auto;padding:36px 24px 72px}}
.hero{{padding-bottom:24px;border-bottom:1px solid var(--line);margin-bottom:26px}}
.badge{{display:inline-block;font-size:11.5px;padding:3px 9px;border-radius:999px;background:rgba(34,211,238,.12);color:var(--cyan);margin-bottom:10px}}
h1{{font-size:28px;color:#f8fafc;letter-spacing:.3px;margin-bottom:8px}}
.lead{{color:var(--txt2);max-width:780px;font-size:14.5px}}
.hero-actions{{margin-top:16px;display:flex;gap:12px;flex-wrap:wrap}}
.btn-primary{{background:var(--cyan);color:#06121e;font-weight:600;padding:8px 16px;border-radius:8px;text-decoration:none;font-size:13.5px}}
.btn-ghost{{border:1px solid var(--line);color:#e2e8f0;padding:8px 16px;border-radius:8px;text-decoration:none;font-size:13.5px;background:var(--panel)}}
.btn-ghost:hover{{border-color:var(--cyan)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px;margin-bottom:26px}}
.card{{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:12px;padding:18px;display:flex;flex-direction:column;justify-content:space-between;text-decoration:none;color:inherit;transition:transform .12s,border-color .15s}}
.card:hover{{transform:translateY(-2px);border-color:var(--cyan)}}
.card .tag{{font-size:11px;color:var(--cyan);margin-bottom:6px;font-family:ui-monospace,monospace}}
.card h2{{font-size:16.5px;color:#f1f5f9;margin-bottom:8px}}
.card p{{font-size:13px;color:var(--txt2);margin-bottom:14px}}
.card .foot{{font-size:12px;color:var(--emerald);font-weight:600}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}
.stat{{background:rgba(15,23,42,.7);border:1px solid var(--line);border-radius:10px;padding:14px}}
.stat .v{{font-size:22px;font-weight:700;color:var(--cyan);font-variant-numeric:tabular-nums}}
.stat .k{{font-size:12px;color:var(--dim);margin-top:2px}}
footer{{margin-top:34px;padding-top:18px;border-top:1px solid var(--line);color:var(--dim);font-size:12px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px}}
footer a{{color:var(--cyan);text-decoration:none}}
</style>
</head>
<body>
<div class="wrap">
  <section class="hero">
    <span class="badge">Open Source · Python 标准库零依赖 · 5000 章超长篇基准</span>
    <h1>novel-lab · 《四界》长篇小说 Agent 工程</h1>
    <p class="lead">围绕「时序正典 Canon + 恒定上下文注入 + 四层确定性大纲 + 两层文体门禁」构建的超长篇生成体系。以下为全部部署的静态可视化页面与《四界》当前已生成章节快照。</p>
    <div class="hero-actions">
      <a class="btn-primary" href="dashboard.html">打开记忆架构大屏</a>
      <a class="btn-ghost" href="outline.html">浏览 5000 章大纲</a>
      <a class="btn-ghost" href="https://github.com/zp-home/novel-lab" target="_blank" rel="noopener">GitHub 开源仓库</a>
    </div>
  </section>

  <section class="grid">
    <a class="card" href="dashboard.html">
      <div>
        <div class="tag">01 / MEMORY ARCHITECTURE</div>
        <h2>长篇记忆架构大屏</h2>
        <p>7 个交互面板：四界 108 阶锯齿战力天梯、7 层存储架构、8 位人物、时序真相甘特图、伏笔账本、恒定上下文注入与 RAG 对比。</p>
      </div>
      <div class="foot">进入大屏 →</div>
    </a>
    <a class="card" href="outline.html">
      <div>
        <div class="tag">02 / OUTLINE BROWSER</div>
        <h2>《四界》5000 章大纲浏览器</h2>
        <p>总纲主脊、{ol_info['acts']} 幕冲突升级、{ol_info['milestones']} 条里程碑、{ol_info['volumes']} 卷 / 500 弧索引，以及前 200 章完整章纲与 4 节拍。</p>
      </div>
      <div class="foot">查看大纲 →</div>
    </a>
    <a class="card" href="progress.html">
      <div>
        <div class="tag">03 / PROGRESS SNAPSHOT</div>
        <h2>正文生成进度看板</h2>
        <p>前 200 章实写进度总览、单章字数与套话/英文污染质检网格、最新章节首尾片段预览。</p>
      </div>
      <div class="foot">已收 {snap['generated']} 章 · 进入看板 →</div>
    </a>
    <a class="card" href="console/">
      <div>
        <div class="tag">04 / WEB CONSOLE (STATIC)</div>
        <h2>Web 控制台只读体验版</h2>
        <p>与本地 web/server.py 同款界面，内置 sijie 已写章节与文体评分快照，支持逐章正文阅读与待修榜单查看。</p>
      </div>
      <div class="foot">已载 {con_info['sijie_chapters']} 章正文 · 打开控制台 →</div>
    </a>
  </section>

  <section class="stats">
    <div class="stat"><div class="v">5,000</div><div class="k">规划总章数（4 界 / 108 阶）</div></div>
    <div class="stat"><div class="v">{snap['generated']} / 200</div><div class="k">首批已落盘章节快照</div></div>
    <div class="stat"><div class="v">{snap['avg']:,} 字</div><div class="k">平均单章汉字数</div></div>
    <div class="stat"><div class="v">10.0%</div><div class="k">1→5000 章上下文漂移</div></div>
  </section>

  <footer>
    <span>快照生成于 {time.strftime("%Y-%m-%d %H:%M:%S")}（Asia/Shanghai）</span>
    <span>开源协议：MIT · <a href="https://github.com/zp-home/novel-lab" target="_blank" rel="noopener">github.com/zp-home/novel-lab</a></span>
  </footer>
</div>
</body>
</html>
"""
    (site / "index.html").write_text(html, encoding="utf-8")


def main() -> int:
    site = ROOT / ".gh-pages-tmp"
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True, exist_ok=True)
    (site / ".nojekyll").write_text("", encoding="utf-8")

    # 1. dashboard.html
    shutil.copy2(ROOT / "out" / "dashboard.html", site / "dashboard.html")

    # 2. outline + progress
    sijie_ol = ROOT / "out" / "sijie" / "outline.json"
    full_ol = ROOT / "out" / "outline_full.json"
    ol_path = sijie_ol if sijie_ol.exists() else full_ol
    book = OL.Book.load(ol_path)
    snap = build_progress(site, book)
    ol_info = build_outline_page(site, ol_path)
    con_info = build_console(site)
    build_index(site, snap, ol_info, con_info)

    print(f"Built static site in {site}")
    print(f"  progress: {snap['generated']}/{snap['target']} chapters, avg={snap['avg']}")
    print(f"  outline:  {ol_info}")
    print(f"  console:  {con_info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
