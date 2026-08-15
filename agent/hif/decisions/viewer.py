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
    "support_card_reinforce": "支援卡强化",
}

# 评分关键词 → 人话(覆盖 decision_keywords.json 全部键;游戏通用术语保持日文原样)
KEYWORD_LABELS = {
    "絶好調[0-9０-９]*ターン": "絶好調N回合",
    "好調[0-9０-９]*ターン": "好調N回合",
    "手札をすべて入れ替える": "全换手牌",
    "入れ替える": "换牌",
    "重複不可": "不可叠加",
    "集中消費": "消耗集中",
    "体力消費": "消耗体力",
    "元気増加無効": "元気无效化",
    "眠気": "眠気(负分)",
    "トラブル": "トラブル(负分)",
    "スキルカード使用数追加": "卡使用数+",
    "スキルカードを2枚引く": "抽卡×2",
    "スキルカードを引く": "抽卡",
    "ターン追加": "回合+",
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
    "support_card_reinforce": "#c0caf5",
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
tr.day-row{cursor:pointer;background:#1f2335}
tr.day-row:hover{background:#2a2f45}
tr.day-row td{padding:6px 10px;border-bottom:1px solid #414868;color:#c0caf5;font-size:12px}
tr.day-row b{color:#7dcfff;margin-right:6px}
tr.group-row{background:#16161e}
tr.group-row:hover{background:#1c2030}
.seq{color:#9aa5ce;font-size:12px}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;white-space:nowrap}
.flag-stop{color:#f7768e}.flag-empty{color:#e0af68}.flag-reroll{color:#7dcfff}.flag-ok{color:#9ece6a}.flag-recovered{color:#ff9e64}
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
const KW = __KW__;
const bySession = {};
DATA.sessions.forEach(s => bySession[s.file] = s.days);
let cur = DATA.sessions.length ? DATA.sessions[DATA.sessions.length - 1].file : null;
const dayOpen = {};
const groupOpen = {};

function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function tagOf(screen){const m=__TAGS__;return m[screen]||screen||'?'}
function colorOf(screen){const m=__COLORS__;return m[screen]||'#9aa5ce'}
function kw(k){return KW[k]||k}
function NOISE(t){
  if(!t||typeof t!=='string')return true;
  if(t.trim().length<=1)return true;
  return ![...t].some(ch=>{
    const c=ch.codePointAt(0);
    return (c>=0x3040&&c<=0x30ff)||(c>=0x4e00&&c<=0x9fff)||/[a-zA-Z0-9]/.test(ch);
  });
}
function cardName(c){return (c&&c!=='?')?esc(c):'<span class="mono-dim">卡名未读</span>'}

function summarize(rec){
  const cands = rec.candidates;
  if (Array.isArray(cands) && cands.length && typeof cands[0]==='object' && 'score' in cands[0]){
    const parts = cands.map(c=>`${cardName(c.card)}=${(+c.score).toFixed(0)}`);
    return `[${parts.join(', ')}] → ${rec.chosen_card?cardName(rec.chosen_card):(esc(rec.chosen)??'?')}`;
  }
  if (Array.isArray(cands) && cands.length) {
    const clean = cands.filter(c=>!NOISE(c));
    const head = clean.slice(0,3).map(esc).join(' / ');
    const rest = clean.length>3?` 等 ${clean.length} 项`:'';
    const tail = clean.length?head+rest:'（候选均为OCR碎片）';
    return `${tail} → ${esc(rec.chosen)}`;
  }
  return esc(rec.chosen||rec.reason||rec.mode||rec.policy||'');
}

function flags(rec){
  let f='';
  if(rec.action==='stop') f+='<span class="flag-stop">■停止</span> ';
  if(rec.evidence_empty) f+='<span class="flag-empty">⚠空证据</span> ';
  if(rec.recovered) f+='<span class="flag-recovered">⟲重建</span> ';
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
      const bd=(c.breakdown||[]).map(([k,v])=>`${esc(kw(k))}<b>${v>0?'+':''}${v}</b>`).join(' ');
      h+=`<tr><td class="num">${c.label??''}</td><td>${cardName(c.card)}</td><td class="num">${(+c.score).toFixed(0)}</td><td class="bd">${bd||'-'}</td><td>${esc((c.text||'').slice(0,80))}</td></tr>`;
    });
    h+='</table>';
  } else if (rec.lines && rec.lines.length){
    h+='<table class="cands"><tr><th>行</th><th>分</th><th>明细</th></tr>';
    rec.lines.forEach(l=>{const bd=(l.breakdown||[]).map(([k,v])=>`${esc(kw(k))}<b>${v>0?'+':''}${v}</b>`).join(' ');h+=`<tr><td>${esc(l.text)}</td><td class="num">${(+l.score).toFixed(0)}</td><td class="bd">${bd||'-'}</td></tr>`});
    h+='</table>';
  }
  if (rec.overrides) h+=`<div>调参: <span class="flag-ok">${esc(JSON.stringify(rec.overrides))}</span></div>`;
  if (rec.reason) h+=`<div class="flag-stop">原因: ${esc(rec.reason)}</div>`;
  for (const k of ['day_remaining','health','priority','names','scrolls','initial_remain','final_remain','checkboxes','card_names','good_condition_cards','accept_threshold','best_score','best_text','source'])
    if (rec[k]!==undefined) h+=`<div class="mono-dim">${k}: ${esc(JSON.stringify(rec[k]))}</div>`;
  if (rec.image) h+=`<img class="shot" src="${esc(rec.image.split(/[\\\\/]/).pop())}" onclick="document.getElementById('lb').src=this.src;document.getElementById('lightbox').style.display='block'" alt="决策截图">`;
  return h||'<span class="mono-dim">（无明细）</span>';
}

function groupSummary(records){
  const seq = records.map(r=>(r.chosen_card&&r.chosen_card!=='?')?r.chosen_card:(r.chosen||r.reason||'')).filter(Boolean);
  const head = seq.slice(0,3).map(esc).join(' → ');
  return head ? head+(seq.length>3?` …（共 ${records.length} 条）`:'') : esc(records[0].mode||'');
}

function matchRec(rec){
  const q=document.getElementById('q').value.trim();
  if(q && !JSON.stringify(rec).includes(q)) return false;
  if(document.getElementById('f-stop').checked && rec.action!=='stop') return false;
  if(document.getElementById('f-empty').checked && !rec.evidence_empty) return false;
  if(document.getElementById('f-reroll').checked && rec.action!=='reroll') return false;
  if(document.getElementById('f-tuned').checked && !rec.overrides) return false;
  if(document.getElementById('f-recovered').checked && !rec.recovered) return false;
  return true;
}
function anyFilter(){
  return document.getElementById('q').value.trim()
    ||document.getElementById('f-stop').checked
    ||document.getElementById('f-empty').checked
    ||document.getElementById('f-reroll').checked
    ||document.getElementById('f-tuned').checked
    ||document.getElementById('f-recovered').checked;
}

function appendRecordRow(body, rec, dayLabel){
  const screen=rec.screen||'?';
  const row=document.createElement('tr');
  row.className='row';
  row.innerHTML=`<td>${esc(rec.ts)}</td><td>${esc(dayLabel)}</td><td><span class="tag" style="background:${colorOf(screen)}22;color:${colorOf(screen)}">${tagOf(screen)}</span></td><td>${esc(rec.action)}</td><td>${summarize(rec)}</td><td>${rec.overrides?'<span class="flag-ok">有</span>':''}</td><td>${flags(rec)}</td>`;
  const det=document.createElement('tr');
  det.className='detail';
  det.innerHTML=`<td colspan="7">${detailHtml(rec)}</td>`;
  row.onclick=()=>det.classList.toggle('open');
  body.appendChild(row);body.appendChild(det);
}

function render(){
  const days = bySession[cur]||[];
  const filtering = anyFilter();
  const body=document.getElementById('rows');
  body.innerHTML='';
  let shown=0, total=0;
  days.forEach(day=>{
    const dayTotal = day.groups.reduce((n,g)=>n+g.records.length,0);
    total += dayTotal;
    if(filtering){
      const hits = day.groups.reduce((n,g)=>n+g.records.filter(matchRec).length,0);
      if(!hits) return;
      shown += hits;
    } else shown += dayTotal;

    const key=`${cur}|${day.label}`;
    const open = filtering ? true : dayOpen[key]===true;
    const stat = day.groups.map(g=>`${tagOf(g.screen)}×${g.records.length}`).join(' · ');
    const head=document.createElement('tr');
    head.className='day-row';
    head.innerHTML=`<td colspan="7">${open?'▾':'▸'} <b>${esc(day.label)}</b><span class="mono-dim">${esc(stat)}</span></td>`;
    head.onclick=()=>{dayOpen[key]=!dayOpen[key];render()};
    body.appendChild(head);
    if(!open) return;

    day.groups.forEach((g,gi)=>{
      if(filtering && !g.records.some(matchRec)) return;
      if(g.records.length===1){
        appendRecordRow(body, g.records[0], day.label);
        return;
      }
      const gk=`${key}|${gi}`;
      const gOpen=groupOpen[gk]===true;
      const screen=g.screen||'?';
      const agg=[...new Set(g.records.flatMap(r=>{
        const parts=[];
        if(r.action==='stop')parts.push('<span class="flag-stop">■停止</span>');
        if(r.evidence_empty)parts.push('<span class="flag-empty">⚠空证据</span>');
        if(r.recovered)parts.push('<span class="flag-recovered">⟲重建</span>');
        if(r.action==='reroll')parts.push('<span class="flag-reroll">↻重抽</span>');
        return parts;
      }))].join(' ');
      const row=document.createElement('tr');
      row.className='row group-row';
      row.innerHTML=`<td>${esc(g.records[0].ts)}~${esc(g.records[g.records.length-1].ts)}</td><td>${esc(day.label)}</td><td><span class="tag" style="background:${colorOf(screen)}22;color:${colorOf(screen)}">${tagOf(screen)}</span></td><td>组 ${gOpen?'▾':'▸'}×${g.records.length}</td><td class="seq">${groupSummary(g.records)}</td><td></td><td>${agg}</td>`;
      row.onclick=()=>{groupOpen[gk]=!groupOpen[gk];render()};
      body.appendChild(row);
      if(gOpen){
        const recs = filtering?g.records.filter(matchRec):g.records;
        recs.forEach(r=>appendRecordRow(body, r, day.label));
      }
    });
  });
  document.getElementById('count').textContent=`${shown}/${total} 条`;
}

function initSession(){
  const sel=document.getElementById('session');
  sel.innerHTML='';
  DATA.sessions.slice().reverse().forEach(s=>{
    const n=s.days.reduce((n,d)=>n+d.groups.reduce((m,g)=>m+g.records.length,0),0);
    const o=document.createElement('option');
    o.value=s.file;o.textContent=`${s.file}（${n} 条）`;
    sel.appendChild(o);
  });
  sel.value=cur;
  sel.onchange=()=>{cur=sel.value;render()};
}
document.querySelectorAll('.bar input,.bar #q').forEach(el=>el.addEventListener('input',render));
document.getElementById('lightbox').onclick=()=>document.getElementById('lightbox').style.display='none';
initSession();render();
"""


def _day_label_of(rec: dict) -> str | None:
    """单条记录的 Day 标签:HIF 准备期「本戦まで N 日」→ D{7-N};Round1 起标 R1。"""
    if rec.get("screen") in ("round1_initial",):
        return "R1"
    n = rec.get("day_remaining")
    if n is None:
        return None
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    if n == 0:
        return "本戦"
    if 1 <= n <= 6:
        return f"D{7 - n}"
    return None


def _attach_day_labels(records: list[dict]) -> None:
    """为记录就地附加 _day:自带优先→顺序继承;开头未标段用首个已知 Day 回填(変卡等每日开头环节与随后日程同天)。"""
    labels = []
    cur = None
    for rec in records:
        label = _day_label_of(rec)
        if label is not None:
            cur = label
        labels.append(cur)
    first_known = next((l for l in labels if l), None)
    for rec, label in zip(records, labels):
        rec["_day"] = label or first_known or "?"


def _is_noise_text(text) -> bool:
    """OCR 碎片判定:空/单字符/纯符号(无假名·汉字·字母·数字)视为噪音,汇总列隐藏。"""
    if not text or not isinstance(text, str):
        return True
    if len(text.strip()) <= 1:
        return True
    return not any(
        "\u3040" <= ch <= "\u30ff"  # 假名
        or "\u4e00" <= ch <= "\u9fff"  # 汉字
        or ch.isalpha()
        or ch.isdigit()
        for ch in text
    )


def _build_day_tree(records: list[dict]) -> list[dict]:
    """记录 → Day 分节树:按 _day 分节,节内按同 screen 连续分组(多条组供前端折叠)。

    返回 [{"label": "D1", "groups": [{"screen": ..., "records": [...]}]}]
    """
    days: list[dict] = []
    for rec in records:
        label = rec.get("_day", "?")
        if not days or days[-1]["label"] != label:
            days.append({"label": label, "groups": []})
        groups = days[-1]["groups"]
        screen = rec.get("screen", "?")
        if not groups or groups[-1]["screen"] != screen:
            groups.append({"screen": screen, "records": []})
        groups[-1]["records"].append(rec)
    return days


def load_sessions(decisions_dir: Path = DECISIONS_DIR) -> list[dict]:
    """读全部 session-*.jsonl,返回 [{file, days}](按文件名升序);记录附加 _day 标签并分节分组。"""
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
        _attach_day_labels(records)
        sessions.append({"file": jsonl.name, "days": _build_day_tree(records)})
    return sessions


def render_html(sessions: list[dict]) -> str:
    """生成自包含 HTML(数据内嵌,截图相对路径引用)。"""
    tags = json.dumps(SCREEN_LABELS, ensure_ascii=False)
    colors = json.dumps(SCREEN_COLORS, ensure_ascii=False)
    script = SCRIPT.replace("__DATA__", json.dumps({"sessions": sessions}, ensure_ascii=False))
    script = script.replace("__KW__", json.dumps(KEYWORD_LABELS, ensure_ascii=False))
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
  <label class="chk"><input type="checkbox" id="f-recovered">重建</label>
  <label class="chk"><input type="checkbox" id="f-tuned">调参生效</label>
</div>
<table><thead><tr><th>时间</th><th>Day</th><th>页面</th><th>动作</th><th>候选→选择/原因</th><th>调参</th><th>标记</th></tr></thead>
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
