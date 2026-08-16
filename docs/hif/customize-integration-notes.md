# 特別指導(カスタマイズ)接入备忘

**日期:** 2026-08-16
**状态:** 数据已勘察、暂缓接入(不阻塞模拟器/评分主线;Round2 流程立项时启动)
**机制依据:** [`mechanics.md`](mechanics.md) H12(官方文本「※カスタマイズは特別指導でおこなえます」已确认系统等同)
**触发条件:** Round1→Round2 之间的准备环节(Interval)可对技能卡特别指导,强化效果或数值;実機変卡流程第三步的「训练师选项」疑似同一系统(待験)。

## 1. 数据资产(全部在 `.scrape/gakumasu-diff/`,无需再勘察)

| 表 | 条数 | 关键字段 | 作用 |
| --- | --- | --- | --- |
| `ProduceCardCustomize.yaml` | 340 | `id` / `customizeCount`(次数档 1-3) / `produceCardGrowEffectIds[]`(注入的 grow 效果) / `producePoint`(P 点 20/40/100) | 强化选项本体;两种强化:数值提升链(如 block_add 4→13)与新增效果(cost_reduce / aggressive_add 等) |
| `ProduceCard.yaml`(逐卡挂载) | — | `produceCardCustomizeIds[]` / `maxCustomizeCount` | **流派池 170 卡中 98 张可被指导**(任意档位口径);样例:アイドル魂 max1/2 选项、ファーストステップ+ max3/3 选项 |
| `ProduceCardCustomizeRarityEvaluation.yaml` | 4 | `rarity` → `evaluation`(12) | 定制后稀有度评价 |

注意:挂载在**档位记录级**(同卡不同档 customizeIds 相同,但需逐档检查,部分卡仅 + 档以上挂载)。

## 2. 三个接入点(接手时按此执行)

### 2a. 数据产物(约 0.5 天)
`tools/sync_hif_effects.py` 扩展:
- 新增 `customize` join:`ProduceCardCustomizeRarityEvaluation` 不需要;`ProduceCardCustomize` 按 id 索引,逐卡 `produceCardCustomizeIds` 展开为 `customizes: [{id, count, point, effects: [grow_effect 条目]}]`(grow 效果用现有 `GROW_EFFECT_TAGS` 五族映射,`_grow_effect_entry` 直接复用)。
- 产物落 `assets/data/hif/skill_card_effects.json` 各卡 `customizes` 字段(schema_version 升 3);CI validate 补「customize id 唯一」检查。

### 2b. 评分(约 0.5 天,零新曲线)
- **定制增量分**:`Δscore(卡, 选项) = score(原 effects + 注入 grow effects) − score(原 effects)`——grow 效果的五族映射已覆盖,直接算。
- **三选一潜力项(P2 可选)**:可指导卡加 `customizable_bonus`(小权重,如 `maxCustomizeCount × 0.5` 未缩放),校准定值;一阶项优先级见 `scoring-model-implementation-plan.md`。

### 2c. 模拟器与管线
- 模拟器 Round-only 的效果执行引擎以 grow effect 为执行单元,**被指导卡 = 原效果 + 注入列表**,作 R2 初始状态输入参数(卡组定义带 `customize_ids`),零架构改动。
- 管线:Interval 环节新增「特别指导」决策点(选卡→选选项→确认),复用三选一的点选-评分-确认模式;决策用 2b 的增量分。挂在 Round2 流程(`feat/hif` 后续迭代)立项时一起做。

## 3. 実機待确认(V 类,跑 Round2 时顺带)

1. 変卡流程第三步「训练师选项」是否即本系统(对照页面选项文案与 `ProduceCardCustomize` 的 grow 效果)。
2. 特别指导的 P 点池与 Interval 可指导次数上限(実機 Interval 画面)。
3. 指导后卡名显示规则(「楽観的+」式)与档位关系。

## 4. 关联

- 机制条目:`mechanics.md` H12
- 数据 join 现状:`scoring-model-implementation-plan.md` 实施结果速览(产物 v2)
- 排期位置:模拟器 Round-only → 评分 C2 → **Round2 流程管线(本项在此启动)**
