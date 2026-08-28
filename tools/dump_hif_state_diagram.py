"""从 ProduceHIF.json 机械导出 HIF 管线状态机边表与 Mermaid 可达图，生成 docs/hif/pipeline-state-machine.md 的图表节。"""

import json
from pathlib import Path
from collections import deque

REPO = Path(__file__).resolve().parents[1]
PIPE = REPO / "assets/resource/base/pipeline/ProduceHIF.json"
ENTRY = "ProduceEntryHIF"
JB = "[JumpBack]"

data = json.loads(PIPE.read_text(encoding="utf-8"))


def short(name: str) -> str:
    for pre in ("ProduceChooseHIF", "ProduceHIF", "Produce"):
        if name.startswith(pre):
            return name[len(pre):]
    return name


def rec_desc(node: dict) -> str:
    rec = node.get("recognition") or {}
    t = rec.get("type", "")
    p = rec.get("param") or {}
    if t == "OCR":
        exp = [e.replace(".*", "").strip("^$") for e in (p.get("expected") or [])]
        head = exp[0] if exp else ""
        more = f" 等{len(exp)}条" if len(exp) > 1 else ""
        return f"OCR「{head}」{more}".strip()
    if t == "TemplateMatch":
        tpl = p.get("template") or []
        head = tpl[0] if tpl else ""
        more = f"+{len(tpl) - 1}" if len(tpl) > 1 else ""
        return f"模板 {head}{more}"
    return t or "—"


def act_desc(node: dict) -> str:
    a = node.get("action") or {}
    t = a.get("type", "")
    p = a.get("param") or {}
    if t == "Custom":
        return f"Custom {p.get('custom_action', '')}"
    if t == "Click":
        tg = p.get("target")
        if tg is True:
            return "Click 锚本体"
        if isinstance(tg, list) and tg:
            return f"Click({tg[0]},{tg[1]})"
        return "Click"
    if t == "StopTask":
        return "StopTask"
    return t or "—"


def act_class(node: dict) -> str:
    t = (node.get("action") or {}).get("type", "")
    return {"Custom": "cust", "Click": "click", "StopTask": "stop"}.get(t, "flag")


def targets_of(node: dict):
    out = []
    for raw in node.get("next") or []:
        jb = raw.startswith(JB)
        out.append((raw, raw[len(JB):] if jb else raw, jb, "next"))
    for raw in node.get("on_error") or []:
        out.append((raw, raw, False, "on_error"))
    return out


# ---------- 引用统计 ----------
referenced = set()
for node in data.values():
    for _, tgt, _, _ in targets_of(node):
        referenced.add(tgt)
defined = set(data)
orphans = sorted(n for n in defined if n != ENTRY and n not in referenced)
externals = sorted(referenced - defined)

print(f"节点总数: {len(defined)}；孤儿(未被任何 next/on_error 引用): {orphans}；外部节点: {externals}")
print()

# ---------- ScheduleRoot 出边序表 + 一圈耗时估算 ----------
sched = data["ProduceHIFScheduleRoot"]
spokes = [(i + 1, raw, tgt, jb) for i, raw in enumerate(sched["next"]) for tgt, jb in [(raw[len(JB):] if raw.startswith(JB) else raw, raw.startswith(JB))]]

print("## ScheduleRoot 出边序表（序号=优先级）")
print()
print("| # | 目标 | JB | 识别 | 动作 |")
print("|---|------|----|------|------|")
ocr_n = tpl_n = 0
for idx, raw, tgt, jb in spokes:
    node = data.get(tgt)
    if node:
        r = rec_desc(node)
        if r.startswith("OCR"):
            ocr_n += 1
        elif r.startswith("模板"):
            tpl_n += 1
    else:
        r = "外部"
    print(f"| {idx} | {short(tgt)} | {'Y' if jb else ''} | {r} | {act_desc(node) if node else '—'} |")
print()
est = ocr_n * 2 + tpl_n * 0.3
print(f"一圈耗时估算: OCR锚 {ocr_n} 个 ×~2s + 模板锚 {tpl_n} 个 ×~0.3s ≈ {est:.0f}s （ScheduleRoot timeout=75s）")
print()

# ---------- 附A 全节点总表 ----------
print("## 全节点总表")
print()
print("| 节点 | 识别 | 动作 | next（序号，↻=JB） | timeout | on_error |")
print("|------|------|------|--------------------|---------|----------|")
for name in sorted(data):
    node = data[name]
    nxt = " / ".join(
        f"{i + 1}{'↻' if jb else ''}{short(tgt)}" for i, (_, tgt, jb, kind) in enumerate(targets_of(node)) if kind == "next"
    )
    oe = " / ".join(short(tgt) for _, tgt, _, kind in targets_of(node) if kind == "on_error")
    to = node.get("timeout", "")
    to = f"{to // 1000}s" if isinstance(to, int) else to
    print(f"| {short(name)} | {rec_desc(node)} | {act_desc(node)} | {nxt or '—'} | {to} | {oe or '—'} |")
print()

# ---------- 图C：ScheduleRoot 可达闭包 Mermaid ----------
clusters = [
    ("pos1-7 浮层/弹窗关闭组", 1, 7),
    ("pos8-11 対局入口与通用推进", 8, 11),
    ("pos12-20 報酬/結果/再挑戦", 12, 20),
    ("pos21-27 最終評価/メモリー/Interval", 21, 27),
    ("pos28-40 日程行动子页/公開レッスン子宿主", 28, 40),
    ("pos41 尾部泛词兜底", 41, 41),
]
spoke_idx = {tgt: i + 1 for i, (_, _, tgt, _) in enumerate(spokes)}
spoke_jb = {tgt: jb for _, _, tgt, jb in spokes}

visited = []
seen = set()
q = deque(t for _, _, t, _ in spokes)
while q:
    n = q.popleft()
    if n == "ProduceHIFScheduleRoot":
        continue
    if n in seen or n not in defined:
        continue
    seen.add(n)
    visited.append(n)
    for _, tgt, _, _ in targets_of(data[n]):
        q.append(tgt)

print("## 图C Mermaid（ScheduleRoot 可达闭包，机械生成不漏边）")
print()
print("```mermaid")
print("flowchart TB")
print('    ProduceHIFScheduleRoot["ScheduleRoot · DirectHit<br/>timeout 75s · 41 出边 · on_error→UnknownStop"]:::root')
emitted = set()
for title, lo, hi in clusters:
    members = [t for _, _, t, _ in spokes if lo <= spoke_idx[t] <= hi]
    print(f'    subgraph SG{lo}["{title}"]')
    print("        direction TB")
    for t in members:
        cls = act_class(data[t]) if t in defined else "ext"
        mark = "↻" if spoke_jb[t] else "●"
        lbl = act_desc(data[t]) if t in defined else "外部"
        print(f'        {t}("{spoke_idx[t]}{mark} {short(t)}<br/>{lbl}"):::{cls}')
        emitted.add(t)
    print("    end")
others = [n for n in visited if n not in emitted]
print('    subgraph SGX["子链内部与出口节点（由上述 Flag 的 next 可达）"]')
print("        direction TB")
for n in others:
    cls = act_class(data[n])
    print(f'        {n}("{short(n)}<br/>{act_desc(data[n])}"):::{cls}')
print("    end")
for idx, raw, tgt, jb in spokes:
    print(f'    ProduceHIFScheduleRoot -->|"{idx}{"↻" if jb else ""}"| {tgt}')
print('    ProduceHIFScheduleRoot -.->|"on_error"| ProduceHIFUnknownStop')
for n in visited:
    for i, (raw, tgt, jb, kind) in enumerate(targets_of(data[n])):
        label = f"{i + 1}{'↻' if jb else ''}" if kind == "next" else "on_error"
        arrow = '-.->' if kind == "on_error" else '-->'
        print(f'    {n} {arrow}|"{label}"| {tgt}')
print("    classDef root fill:#dcfce7,stroke:#16a34a,stroke-width:2px")
print("    classDef cust fill:#dbeafe,stroke:#2563eb")
print("    classDef click fill:#ffedd5,stroke:#ea580c")
print("    classDef flag fill:#fef9c3,stroke:#ca8a04")
print("    classDef stop fill:#fee2e2,stroke:#dc2626")
print("    classDef ext fill:#f4f4f5,stroke:#a1a1aa,stroke-dasharray:4")
print("```")
