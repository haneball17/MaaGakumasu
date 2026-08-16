"""trace 注入自包含 HTML(离线降级模式,§8.2)。

用法:
    python tools/render_round_ui.py --preset hif_r1_rinami --seed 42 --out round-trace.html
    python tools/render_round_ui.py --trace some-trace.json --out round-trace.html

两级降级:
1. ui/dist/index.html 存在(已构建):注入 window.__TRACE_DATA__ 占位 → 完整 Vue UI;
2. 未构建(无 node):内嵌原生 JS 最小查看器(回合 scrubber + 得分/状态/牌库表),
   规避 file:// 的 fetch CORS——单文件双击可开,可归档 debug/。
"""

from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.hif.roundsim import PRESETS, run_exam, build_spec  # noqa: E402
from agent.hif.roundsim.strategies import make_strategy  # noqa: E402

UI_DIST = Path(__file__).resolve().parents[1] / "ui" / "dist" / "index.html"
_MARKER = "window.__TRACE_DATA__=null"

_MINIMAL_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>roundsim trace 回放(离线最小视图)</title>
<style>
 body{font-family:system-ui,sans-serif;margin:16px;background:#111;color:#eee}
 h1{font-size:18px} .meta{color:#8f8;font-size:13px}
 input[type=range]{width:100%}
 table{border-collapse:collapse;font-size:13px;width:100%}
 td,th{border:1px solid #444;padding:3px 7px;text-align:left}
 .turn{background:#1c1c1c;padding:8px;border-radius:6px;margin:6px 0}
 .score{color:#ffd866} .zone{color:#79c0ff} .bad{color:#ff7b72}
</style>
</head>
<body>
<h1>roundsim trace 回放(离线最小视图)</h1>
<div class="meta" id="meta"></div>
<input type="range" id="scrub" min="1" max="1" value="1" oninput="render(+this.value)">
<div id="turn"></div>
<h2>回合得分</h2>
<table id="scores"></table>
<script>
window.__TRACE_DATA__=null;
const T=window.__TRACE_DATA__;
const fm=document.getElementById('meta');
fm.textContent=`${T.spec_digest.preset||'custom'} seed=${T.seed} strategy=${T.strategy} `+
  `turns=${T.spec_digest.turns} deck=${T.spec_digest.deck_size} 総分=${T.final.total_score} 順位=${T.final.rank}`;
const scrub=document.getElementById('scrub');
scrub.max=T.turns.length;
function fmt(t){return t?`${t.base_value}+${t.focus_value} ×${t.state_mult} ×${t.param_mult.toFixed(2)} = ${t.points}`:'—';}
function render(i){
  const t=T.turns[i-1];
  document.getElementById('turn').innerHTML=
   `<div class="turn"><b>T${t.turn} 流行 ${t.flow}</b> · 动作 ${t.action.kind}${t.action.card?'('+t.action.card+')':''}`+
   `<br>手牌: ${t.hand_before.join(' / ')||'(空)'}`+
   `<br><span class="score">得分 ${t.turn_score}(主出牌 ${fmt(t.score)}${t.extra_scores.map(x=>' + '+fmt(x)).join('')})</span>`+
   `<br>好調${t.state_after.good_condition_turns}T 絶好調${t.state_after.excellent_condition_turns}T 集中${t.state_after.focus} 体力${t.state_after.stamina} 出牌累计${t.state_after.cards_played}`+
   `<br><span class="zone">牌库 山札${t.zones.deck}/捨札${t.zones.grave}/除外${t.zones.lost}/手札${t.zones.hand}</span>${t.reshuffled?' <span class="bad">[重洗发生]</span>':''}`+
   (t.effects.length?'<br>效果链: '+t.effects.map(e=>`${e.note||e.tag}:${e.detail}`).join('; '):'')+
   (t.triggers.length?'<br>触发: '+t.triggers.map(x=>`${x.source} ${x.note}`).join('; '):'')+
   `</div>`;
}
function renderScores(){
  document.getElementById('scores').innerHTML=
   '<tr><th>回合</th><th>流</th><th>出牌</th><th>得分</th></tr>'+
   T.turns.map(t=>`<tr><td>${t.turn}</td><td>${t.flow}</td><td>${t.action.plays.join(',')||t.action.kind}</td><td>${t.turn_score}</td></tr>`).join('');
}
render(1);renderScores();
</script>
</body>
</html>
"""


def render(trace: dict) -> str:
    """trace dict → 自包含 HTML 文本。"""
    payload = json.dumps(trace, ensure_ascii=False)
    if UI_DIST.exists():
        html = UI_DIST.read_text(encoding="utf-8")
        if _MARKER in html:
            return html.replace(_MARKER, f"window.__TRACE_DATA__={payload}")
    # 降级:内嵌最小查看器(模板里的占位随 payload 一起替换)
    return _MINIMAL_TEMPLATE.replace(_MARKER, f"window.__TRACE_DATA__={payload}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="trace → 自包含离线 HTML")
    parser.add_argument("--preset", default="hif_r1_rinami", choices=sorted(PRESETS))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--strategy", default="garakuta_rinami")
    parser.add_argument("--trace", type=Path, default=None, help="已有 trace JSON 文件(优先于现场模拟)")
    parser.add_argument("--out", type=Path, default=Path("round-trace.html"))
    args = parser.parse_args(argv)

    if args.trace:
        trace = json.loads(args.trace.read_text(encoding="utf-8"))
    else:
        strat = make_strategy(args.strategy) if args.strategy != "skip" else None
        doc = run_exam(build_spec(args.preset), seed=args.seed, strategy=strat, preset_name=args.preset)
        trace = json.loads(doc.model_dump_json())
    html = render(trace)
    args.out.write_text(html, encoding="utf-8")
    mode = "Vue 构建模板" if UI_DIST.exists() else "内嵌最小查看器(未构建降级)"
    print(f"离线 HTML 已生成: {args.out}({mode},双击可开)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
