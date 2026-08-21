# HIF 决策接口审计报告（五轮验证阶段 3，2026-08-22）

> goal 验收条件「决策接口就绪」配套文档：决策点清单 / 三层覆盖链 / strategy 接口 /
> p_items·p_drinks·deck 消费路径 / 缺口清单。

## 1. 决策点清单（Custom action 全景，19 个注册）

| # | action | 决策点 | 输入 | 决策逻辑 | 落盘 screen |
| --- | --- | --- | --- | --- | --- |
| 1 | ProduceChooseHIFEventAuto | 日程选择 | 色扫/OCR/模板候选+体力+日数 | 低体力→おでかけ；preset 日程序 priority | finals_action_select |
| 2 | ProduceChooseHIFPItemAuto | 准备段 P 道具 | 推荐/关键词 OCR | 推荐模板→关键词序（Pポイント>相談>Pドリンク） | hif_p_item_select |
| 3 | ProduceChooseHIFClassOptionAuto | 授業选项 | OCR 选项行 | 好调文案>获得类>first_safe；防循环 recent | hif_class_options |
| 4 | ProduceChooseHIFDrinkRewardAuto | P 饮料三选一 | 逐张点选读卡名+效果 | 名单优先>模型分(score_drink_by_name)>关键词 | hif_drink_reward |
| 5 | ProduceChooseHIFSkillRewardAuto | 技能卡三选一 | 同上 | 名单>模型分(score_card_by_name)>关键词+再抽選 | hif_skill_reward |
| 6 | ProduceChooseHIFSelectChangeTargetAuto | 変卡目标 | 同三选一 | 评分+重抽 | select_change_target |
| 7 | ProduceChooseHIFSelectChangeSourceAuto | 変卡源卡 | 全库扫描（3×4 网格滚动） | 名单序>首格 fallback | select_change_source_deck |
| 8 | ProduceHIFConsultAuto | 相談商店 | — | finish_without_purchase（首版） | consult_shop |
| 9 | ProduceChooseHIFSPCardAuto | SP 效果卡 | OCR 行 | 关键词评分最高行>第一张 | hif_sp_card_select |
| 10 | ProduceChooseHIFDrinkOverflowAuto | 饮料上限取舍 | 色扫勾选框+あとN個 | 补勾至归零→残す | hif_drink_overflow |
| 11 | ProduceHIFSelectChangeDoneAuto | 変卡演出推进 | — | 点空白 | select_change_done |
| 12 | ProduceHIFChooseIdolAuto | 偶像校验 | OCR 名字/曲名 | SequenceMatcher 校验>プロデュース開始 | hif_idol_select |
| 13 | ProduceHIFStartConfirmAuto | 開始確認 | — | 默认编成開始+源卡名单校验 | hif_start_confirm |
| 14 | ProduceHIFChooseFinalModeAuto | 本戦入口 | — | entry_mode 校验+点击 | hif_mode_select |
| 15 | ProduceHIFRound1Observe | R1 观察 | read_hand | 只记录 | round1_initial |
| 16 | **ProduceHIFRound1Play** | **R1/R2 出牌**（参数化 9/12T） | 残りターン/体力/flow/buff 模板/手牌 YOLO/再演双源/**P 饮料槽/P item 縦列/牌堆(假设)** | GarakutaRinamiStrategy.decide(state) | round1_play/round2_play |
| 17 | ProduceHIFPDrinkObtainedAuto | 培育段饮料获得捕获 | 名称行 OCR | match_drink_name 库匹配（无决策，只记录） | p_drink_obtained |
| 18 | ProduceHIFIntervalAuto | Interval 推进 | 終了按钮 | 首版直接終了（P 点消费探索轮放开） | hif_interval |
| 19 | ProduceHIFRetryConfirmAuto | 再挑戦確認 | — | プロデュース終了（goal 裁决：敗退走结算） | hif_retry_confirm |
| 20 | ProduceHIFMemoryDetailNextAuto | メモリー詳細推进 | 次へ OCR | OCR 锚定点击+浏览页 BACK 自愈 | （无决策） |

## 2. 三层覆盖链（实测生效）

```
GUI 选项（produce_cn/produce.json case → pipeline_override → custom_action_param）
  > decision_override.json（debug/decisions/，非评分项：名单/重抽/低体力/逐日/策略）
  > 倾向基准（preference 基准表）
  > preset 默认（presets.py SAFE_DEFAULT_PRESET / rinami_good_condition_safe）
```

- 解析入口：`parse_hif_preset(custom_action_param)` → `apply_file_overrides()`（produce_hif.py `_get_preset`）。
- 実証：轮 0/轮 1 以 GUI 选项「莉波好调（实验）+Round1 出牌=Yes+使用体力药=Yes」注入，preset_id=rinami_good_condition_safe 到达全部 Flag；round1_mode=play 切 PlayFlag。

## 3. strategy 接口（GarakutaRinamiStrategy）

```python
class GarakutaRinamiStrategy:
    def __init__(self, payload: ProfilePayload): ...
    def decide(self, state: ExamState) -> CardAction:  # play.py:55
```

- 输入 ExamState（含全部対局字段）；输出 CardAction(kind=PLAY_CARD/SKIP/USE_P_DRINK, target_card, reason)。
- 消费的 ExamState 字段（現策略）：turn/total_turns/good_condition_turns/focus/stamina/hand/deck_size/oneesan_used/natural_finisher_used/reprise_count/**available_p_drinks**（_pick_drink, play.py:142）。
- USE_P_DRINK 被执行层拦截（Q9 瓶位语义未定案）降级 SKIP——记录不点击。
- round 字段（HONSEN_R1/R2）：策略不分支（两轮同策略，goal 裁决）。

## 4. p_items / p_drinks / deck 消费路径（2026-08-22 新接口）

```
识别层（Round1Play 开局，on_battle_page 守卫）
  _probe_p_drink_slots   → 4 槽逐个点开弹窗读名 → match_drink_name → session.p_drink_slots
  _read_p_item_details   → 縦列图标点开详情弹窗（滚动骨架）→ match_pitem_name 分段 → session.p_items
  _read_deck_state       → 牌堆查看器（假设位，UI 未実機取证）→ session.deck_state
    ↓ session-state.json（round1 子树）
_build_state（每回合）
  → ExamState.p_items / p_drinks / deck + available_p_drinks（槽表名单）
    ↓
决策层（decide(state)）——現策略只消费 available_p_drinks；
  p_items/p_drinks/deck 为后续策略/审计接口就绪（字段语义见 state.py 注释）
    ↓
落盘：round{1,2}_play JSONL evidence（p_items/p_drink_slots 每回合随 evidence 记录）
```

実証状态（2026-08-22 轮 0/1）：
- p_drinks：✓ 槽探测+库匹配（初星黒酢 命中）+JSONL
- p_items：部分 ✓（弹窗结构実機取证 pitem2_detail.png；入口坐标待校准，miss 降级）
- deck：未 ✓（查看器 UI 未取证，假设位 miss 降级——探索轮校准）

## 5. 缺口清单

| # | 缺口 | 影响 | 计划 |
| --- | --- | --- | --- |
| 1 | P item 详情入口坐标（縦列图标位与 buff 带/排名区交叠） | p_items 读不到（降级不阻断） | 探索轮 SoM 定位实际图标位 |
| 2 | 牌堆查看器 UI 未取证（指示器位置假设） | deck 三堆读不到 | 探索轮実機找山札/捨て札入口 |
| 3 | USE_P_DRINK 瓶位语义未定案（A5） | 饮料使用被拦截 | 実機点击瓶位观察效果后放行 |
| 4 | GarakutaRinami 不消费 p_items/deck/round | 决策质量不评判（goal 裁决） | 后续策略升级 |
| 5 | 相談商店只 finish_without_purchase | P 点消费机会丢失 | 探索轮商店流取证后实现 |
| 6 | Interval 只終了直进 | 同上 | 探索轮（リフレッシュ/特別指導等放开） |
| 7 | メモリー再生成/変換不点 | 探索项 | 探索轮分支 |
| 8 | R2 勝利流未実機取证 | 勝利时路由未知 | 轮 3-5 若勝利观察 |
| 9 | 変卡/差し入れ后 IPC 偶发 hang（bug#15） | 段卡死需接力 | maafw 升级或 agent 侧超时守卫 |
