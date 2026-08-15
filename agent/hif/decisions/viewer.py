"""HIF 决策日志 HTML 查看器:读 debug/decisions/session-*.jsonl 生成自包含 decisions.html。

架构位置:决策包内纯函数(无 maafw 依赖,pytest 可测);produce_hif 的 _archive_decision
在每次写 JSONL 后自动重生成(tools/hif_decision_viewer.py 是手动 CLI 薄壳)。

特性:深色终端风时间线、点击行展开候选评分明细、截图预览(点击放大)、
页面类型/标记过滤、多 session 下拉切换。截图以相对路径引用(HTML 与 png 同目录)。
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DECISIONS_DIR = REPO / "debug" / "decisions"
OUT_NAME = "decisions.html"

SCREEN_LABELS = {
    "finals_action_select": "日程",
    "hif_class_options": "授業选项",
    "select_change_target": "変卡目标",
    "select_change_source_deck": "変卡源牌",
    "select_change_done": "変卡完成",
    "hif_drink_reward": "饮料",
    "hif_skill_reward": "技能卡",
    "hif_sp_card_select": "SP效果卡",
    "hif_drink_overflow": "上限页",
    "consult_shop": "相談",
    "hif_p_item_select": "P道具",
    "round1_initial": "Round1",
    "unknown_stop": "安全停止",
}

# 页面标签配色(深色底下的柔和彩)
SCREEN_COLORS = {
    "finals_action_select": "#7aa2f7",
    "hif_class_options": "#bb9af7",
    "select_change_target": "#9ece6a",
    "select_change_source_deck": "#73daca",
    "select_change_done": "#414868",
    "hif_drink_reward": "#e0af68",
    "hif_skill_reward": "#aa7ff0",
    "hif_sp_card_select": "#ff9e64",
    "hif_drink_overflow": "#f7768e",
    "consult_shop": "#89ddff",
    "hif_p_item_select": "#b4f9f8",
    "round1_initial": "#ff757f",
    "unknown_stop": "#db4b4b",
}

STYLE = """
:root{color-scheme:dark}
*{box-sizing:border-box;margin:0;padding:0}
body{background:#1a1b26;color:#c0caf5;font:13px/1.5 "Cascadia Code","Consolas",monospace;padding:16px}
h1{font-size:15px;color:#7aa2f7;margin-bottom:4px}
.sub{color:#565f89;font-size:11px;margin-bottom:12px}
.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
select,input[type=text]{background:#24283b;color:#c0caf5;border:1px solid #414868;border-radius:4px;padding:4px 8px;font:inherit}
label.chk{display:flex;gap:4px;align-items:center;color:#9aa5ce;cursor:pointer;font-size:12px}
table{width:100%;border-collapse:collapse}
th{position:sticky;top:0;background:#1f2335;color:#7aa2f7;text-align:left;padding:6px 10px;border-bottom:1px solid #414868;font-size:12px}
td{padding:5px 10px;border-bottom:1px solid #24283b;vertical-align:top}
tr.row{cursor:pointer}
tr.row:hover{background:#24283b}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;white-space:nowrap}
.flag-stop{color:#f7768e}.flag-empty{color:#e0af68}.flag-reroll{color:#7dcfff}.flag-ok{color:#9ece6a}
.detail{display:none;background:#16161e}
.detail.open{display:table-row}
.detail>td{padding:10px 14px}
.cands{width:100%;border-collapse:collapse;margin-bottom:8px}
.cands td,.cands th{border:1px solid #2f334d;padding:4px 8px;font-size:12px}
.cands .num{text-align:right}
.bd{color:#9aa5ce}.bd b{color:#9ece6a;font-weight:normal}.bd i{color:#f7768e;font-style:normal}
#lightbox{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:9;cursor:zoom-out;text-align:center}
#lightbox img{max-width:96vw;max-height:96vh;margin:2vh auto}
.shot{max-width:180px;border:1px solid #414868;border-radius:4px;cursor:zoom-in;display:block}
.mono-dim{color:#565f89}
"""

SCRIPT = """
const DATA = __DATA__;
const bySession = {};
DATA.sessions.forEach(s => bySession[s.file] = s.records);
let cur = DATA.sessions.length ? DATA.sessions[DATA.sessions.length - 1].file : null;

function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function tagOf(screen){const m=__TAGS__;return m[screen]||screen||'?'}
function colorOf(screen){const m=__COLORS__;return m[screen]||'#9aa5ce'}

function summarize(rec){
  const cands = rec.candidates;
  if (Array.isArray(cands) && cands.length && typeof cands[0]==='object' && 'score' in cands[0]){
    const parts = cands.map(c=>`${c.card||'?'}=${(+c.score).toFixed(0)}`);
    return `[${parts.join(', ')}] → ${rec.chosen_card||rec.chosen||'?'}`;
  }
  if (Array.isArray(cands) && cands.length) return `${cands.map(esc).join(' / ')} → ${esc(rec.chosen)}`;
  return esc(rec.chosen||rec.reason||rec.mode||rec.policy||'');
}

function flags(rec){
  let f='';
  if(rec.action==='stop') f+='<span class="flag-stop">■停止</span> ';
  if(rec.evidence_empty) f+='<span class="flag-empty">⚠空证据</span> ';
  if(rec.action==='reroll') f+='<span class="flag-reroll">↻重抽</span> ';
  if(rec.action==='confirm'||rec.action==='pick'||rec.action==='pick_event'||rec.action==='pick_option'||rec.action==='pick_line'||rec.action==='pick_source'||rec.action==='keep_submit'||rec.action==='finish_without_purchase'||rec.action==='observe'||rec.action==='blank_tap') f+='<span class="flag-ok">✓</span>';
  return f;
}

function detailHtml(rec){
  let h='';
  const cands=rec.candidates;
  if (Array.isArray(cands)&&cands.length&&typeof cands[0]==='object'&&'breakdown' in cands[0]){
    h+='<table class="cands"><tr><th>#</th><th>卡名</th><th>分</th><th>评分明细</th><th>效果原文</th></tr>';
    cands.forEach(c=>{
      const bd=(c.breakdown||[]).map(([k,v])=>`${esc(k)}<b>${v>0?'+':''}${v}</b>`).join(' ');
      h+=`<tr><td class="num">${c.label??''}</td><td>${esc(c.card)||'<span class="mono-dim">未读</span>'}</td><td class="num">${(+c.score).toFixed(0)}</td><td class="bd">${bd||'-'}</td><td>${esc((c.text||'').slice(0,80))}</td></tr>`;
    });
    h+='</table>';
  } else if (rec.lines && rec.lines.length){
    h+='<table class="cands"><tr><th>行</th><th>分</th><th>明细</th></tr>';
    rec.lines.forEach(l=>{const bd=(l.breakdown||[]).map(([k,v])=>`${esc(k)}<b>${v>0?'+':''}${v}</b>`).join(' ');h+=`<tr><td>${esc(l.text)}</td><td class="num">${(+l.score).toFixed(0)}</td><td class="bd">${bd||'-'}</td></tr>`});
    h+='</table>';
  }
  if (rec.overrides) h+=`<div>调参: <span class="flag-ok">${esc(JSON.stringify(rec.overrides))}</span></div>`;
  if (rec.reason) h+=`<div class="flag-stop">原因: ${esc(rec.reason)}</div>`;
  for (const k of ['day_remaining','health','priority','names','scrolls','initial_remain','final_remain','checkbox_x','card_names','good_condition_cards','accept_threshold'])
    if (rec[k]!==undefined) h+=`<div class="mono-dim">${k}: ${esc(JSON.stringify(rec[k]))}</div>`;
  if (rec.image) h+=`<img class="shot" src="${esc(rec.image.split(/[\\\\/]/).pop())}" onclick="document.getElementById('lb').src=this.src;document.getElementById('lightbox').style.display='block'" alt="决策截图">`;
  return h||'<span class="mono-dim">（无明细）</span>';
}

function render(){
  const recs=(bySession[cur]||[]).map(r=>r);
  const q=document.getElementById('q').value.trim();
  const onlyStop=document.getElementById('f-stop').checked;
  const onlyEmpty=document.getElementById('f-empty').checked;
  const onlyReroll=document.getElementById('f-reroll').checked;
  const onlyTuned=document.getElementById('f-tuned').checked;
  const body=document.getElementById('rows');
  body.innerHTML='';
  let shown=0;
  recs.forEach((rec,i)=>{
    if(q && !JSON.stringify(rec).includes(q)) return;
    if(onlyStop && rec.action!=='stop') return;
    if(onlyEmpty && !rec.evidence_empty) return;
    if(onlyReroll && rec.action!=='reroll') return;
    if(onlyTuned && !rec.overrides) return;
    shown++;
    const screen=rec.screen||'?';
    const row=document.createElement('tr');
    row.className='row';
    row.innerHTML=`<td>${esc(rec.ts)}</td><td><span class="tag" style="background:${colorOf(screen)}22;color:${colorOf(screen)}">${tagOf(screen)}</span></td><td>${esc(rec.action)}</td><td>${summarize(rec)}</td><td>${rec.overrides?'<span class="flag-ok">有</span>':''}</td><td>${flags(rec)}</td>`;
    const det=document.createElement('tr');
    det.className='detail';
    det.innerHTML=`<td colspan="6">${detailHtml(rec)}</td>`;
    row.onclick=()=>det.classList.toggle('open');
    body.appendChild(row);body.appendChild(det);
  });
  document.getElementById('count').textContent=`${shown}/${recs.length} 条`;
}

function initSession(){
  const sel=document.getElementById('session');
  sel.innerHTML='';
  DATA.sessions.slice().reverse().forEach(s=>{
    const o=document.createElement('option');
    o.value=s.file;o.textContent=`${s.file}（${s.records.length} 条）`;
    sel.appendChild(o);
  });
  sel.value=cur;
  sel.onchange=()=>{cur=sel.value;render()};
}
document.querySelectorAll('.bar input,.bar #q').forEach(el=>el.addEventListener('input',render));
document.getElementById('lightbox').onclick=()=>document.getElementById('lightbox').style.display='none';
initSession();render();
"""


def load_sessions(decisions_dir: Path = DECISIONS_DIR) -> list[dict]:
    """读全部 session-*.jsonl,返回 [{file, records}](按文件名升序)。"""
    sessions = []
    for jsonl in sorted(decisions_dir.glob("session-*.jsonl")):
        records = []
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        sessions.append({"file": jsonl.name, "records": records})
    return sessions


def render_html(sessions: list[dict]) -> str:
    """生成自包含 HTML(数据内嵌,截图相对路径引用)。"""
    tags = json.dumps(SCREEN_LABELS, ensure_ascii=False)
    colors = json.dumps(SCREEN_COLORS, ensure_ascii=False)
    script = SCRIPT.replace("__DATA__", json.dumps({"sessions": sessions}, ensure_ascii=False))
    script = script.replace("__TAGS__", tags).replace("__COLORS__", colors)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>HIF 决策日志</title><style>{STYLE}</style></head>
<body>
<h1>HIF 决策日志查看器</h1>
<div class="sub">debug/decisions/ · 点击行展开明细 · 点击截图放大 · <span id="count"></span></div>
<div class="bar">
  <select id="session"></select>
  <input type="text" id="q" placeholder="搜索任意字段…">
  <label class="chk"><input type="checkbox" id="f-stop">停止</label>
  <label class="chk"><input type="checkbox" id="f-empty">空证据</label>
  <label class="chk"><input type="checkbox" id="f-reroll">重抽</label>
  <label class="chk"><input type="checkbox" id="f-tuned">调参生效</label>
</div>
<table><thead><tr><th>时间</th><th>页面</th><th>动作</th><th>候选→选择/原因</th><th>调参</th><th>标记</th></tr></thead>
<tbody id="rows"></tbody></table>
<div id="lightbox"><img id="lb" alt=""></div>
<script>{script}</script>
</body></html>
"""


def refresh(decisions_dir: Path = DECISIONS_DIR) -> Path | None:
    """重生成 HTML;无 session 时返回 None。供 _archive_decision 自动调用。"""
    sessions = load_sessions(decisions_dir)
    if not sessions:
        return None
    out = decisions_dir / OUT_NAME
    out.write_text(render_html(sessions), encoding="utf-8")
    return out


def main() -> int:
    out = refresh()
    if not out:
        print("无 debug/decisions/session-*.jsonl")
        return 1
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
