# HIF 决策参数覆盖参考

决策覆盖优先级链（grill 2026-08-15 定案）：

```
GUI「HIF 决策微调」输入（MFA 任务配置） > decision_override.json 文件 > 培育倾向基准（decision_keywords.json） > preset 默认
```

- **点名覆盖**：只改点名的参数，未点名项保持所选倾向基准（莉波荆棘之路绑好调系，在「培育倾向」选一次即可）
- **容错**：非法项（关键词不在表/数值类型错/JSON 语法错）忽略并写日志警告，其余部分生效
- **可核对**：每次三选一决策写入 `debug/decisions/session-<日期>.jsonl`，含评分明细与 `overrides`（当前生效的 GUI 调参），截图同目录存档

## 覆盖方式一：GUI（推荐）

MFA 任务配置「开始培育 → HIF 决策微调」，全部输入框留默认（0/空）= 不覆盖：

| 输入框 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| 预设ID | 文本 | safe_default | `safe_default` / `rinami_good_condition_safe`；本组任一非默认值生效后以本组为准（与「HIF预设」下拉二选一使用） |
| 培育倾向值 | 文本 | good_condition | `good_condition` / `focus` / `balanced`（同「培育倾向」下拉） |
| 好调权重 | 整数 | 0 | 好調Nターン 分值（絶好調联动 = 此值+2），0=用倾向基准 |
| 集中权重 | 整数 | 0 | 集中 分值 |
| 体力回复权重 | 整数 | 0 | 体力回復 分值 |
| 重抽阈值 | 整数 | 0 | 三选一最高分低于此值且可重抽时重抽（默认 4） |
| 変卡重抽上限 | 整数 | 0 | 默认 3 |
| 奖励重抽上限 | 整数 | 0 | 默认 2 |
| 低体力百分比 | 整数 | 0 | 体力低于此百分比日程强制おでかけ（默认 35） |
| 卡牌优先名单 | 文本 | 空 | 逗号分隔卡名，命中直接选不评分（変卡目标/技能卡奖励页） |
| 饮料优先名单 | 文本 | 空 | 逗号分隔饮料名（饮料三选一页） |
| Day1~Day6 日程序 | 文本×6 | 空 | 逗号分隔优先序，可用键 `Vo/Da/Vi/gift/consult/go_out`（如 `Da,Vi,Vo`），留空用预设逐日表 |

卡名/饮料名可用值：`assets/data/hif/skill_cards_master.json`（121 卡）与 `drinks.json`（28 种）。

## 覆盖方式二：文件（全量兜底）

编辑 `assets/data/hif/decision_override.json`（`_` 前缀键为说明，解析时忽略）：

| 键 | 类型 | 对应 GUI | 说明 |
| --- | --- | --- | --- |
| `keyword_weights` | 对象 | 无（GUI 只有三个常用词） | 任意关键词分值覆盖，键须与 `decision_keywords.json` 所选倾向的关键词完全一致（含正则字符），如 `"好調[0-9０-９]*ターン": 9` |
| `negative_weights` | 对象 | 无 | 负面关键词分值，如 `"トラブル": -20` |
| `accept_threshold` | 数 | 重抽阈值 | 0=不覆盖 |
| `card_priority` | 数组 | 卡牌优先名单 | `["始まりの合図", "大胆不敵"]` |
| `drink_priority` | 数组 | 饮料优先名单 | `["センブリソーダ"]` |
| `select_change_reroll_limit` | 数 | 変卡重抽上限 | 0=不覆盖 |
| `reward_reroll_limit` | 数 | 奖励重抽上限 | 0=不覆盖 |
| `low_health_percent` | 数 | 低体力百分比 | 0=不覆盖 |
| `daily_schedule` | 对象 | Day1~6 日程序 | 键为剩余日数（`"6": "Vo,Da,Vi"`，Day1=6…Day6=1） |
| `consult_policy` | 文本 | 无 | 当前仅 `finish_without_purchase` |
| `class_option_policy` | 文本 | 无 | 当前仅 `first_safe` |

GUI 与文件同时配置时 GUI 优先；GUI 已覆盖的项不再取文件值。

## 关键词表基准（decision_keywords.json）

好调系（good_condition）正面词基准：絶好調Nターン 8 / 好調Nターン 6 / 再演 5 / スキルカード使用数追加 4 / スキルカードを2枚引く 4 / レッスン中強化 4 / ターン追加 6 / 体力回復 5 / パラメータ 2 / 集中 2 / 元気 1。
负面词基准：トラブル -12 / 眠気 -8 / 元気増加無効 -5 / 手札をすべて入れ替える -3 / 入れ替える -2 / 重複不可 -1 / 集中消費 -1 / 体力消費 -1。

评分规则（rewards.py）：
- 全/半角**括号内条件文案不计分**（如「パラメータ+30（好調効果を2倍適用）」）
- 好調/絶好調 只按「Nターン」句式计分（防「好調状態の場合」类条件词误中）
- 负面词先行移除、长词优先、命中即移除（防子串重复计分）
- OCR 误识变体归一（`ocr_variants` 表）先于评分

## 决策日志（debug/decisions/）

- `session-YYYYMMDD.jsonl`：每行一次决策——时间、页面、倾向、各候选（卡名/效果原文/分数/评分明细）、选择、生效的 overrides、阈值
- `<时间戳>_<页面>.png`：决策时页面截图
- 复盘方法：对照 JSONL 的 `breakdown` 看每个候选为什么赢/输；调整权重后跑对照局验证 `overrides` 字段确已生效
