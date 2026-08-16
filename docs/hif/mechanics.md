# HIF 本戦 游戏机制知识库

**日期:** 2026-08-16(三路联网调研 + 本地数据交叉复核)
**状态:** 初稿,待逐条审(见文末清单)
**来源:** 本地実機日志/数据 dump(最高置信)> 官方(famitsu/公式X)> 攻略站(Game8/gamerch/学マスwiki)> 社区检证(note/X/博客)
**用途:** 评分模型(scoring.py)修正与模拟器(simulator)建设的机制依据;每条带置信度与実機验证状态。

置信度图例:**A**=本地数据/実機实证;**B**=多源一致(含官方或攻略站);**C**=单源或社区检证;**D**=推测/有冲突待裁。

---

## 1. 本戦结构与回合(章节:M1-M4)

### M1 本戦全体结构【B】
本戦 = 准备期(6 天日程 + 当日)→ ラウンド1(9 ターン)→ インターバル → ラウンド2(12 ターン)。
メモリー(選抜試験产物)可无限重挑;ドリンク与 P ポイント不能带入本戦。
来源:game8 783836、wikiwiki HIF/基本情報;本地実機(Round1 残りターン9 実証)。

### M2 准备期日程【A+B】
実機记录为 6 天日程选择(Day1-6 各有授業/レッスン/おでかけ/差し入れ/相談);game8 表述为「レッスンと授業各 2 次固定,自由选择仅 3 日目(おでかけ or 差し入れ)」。两者不矛盾(game8 是最简描述),以実機日志为准:存在相談(最終日)与差し入れ。
来源:実機 session-20260815.jsonl;game8 783836。

### M3 手札与抽牌【A 官方】
**官方常量(ExamSetting.yaml):`turnStartDistribute: 3`(每回合开始分发 3 张)、`handLimit: 5`(手札上限 5)、`holdLimit: 2`(保留上限 2)**。回合结束时手札全部进捨て札,下回合重发;Hold 效果可保留(≤2 张,故上限 3+2=5——官方 bug 公告「5 枚以上卡死」吻合)。
来源:ExamSetting.yaml + famitsu/公式X;本地実機初始 3 张吻合。

### S8 状态倍率与指針官方常量表【A 数据实证;集中语义修正】
`ExamSetting.yaml`(单条全局配置)关键常量(permil=千分率):
| 常量 | 值 | 语义 |
| --- | --- | --- |
| examParameterBuffPermil | 1500 | 好調 ×1.5 |
| examParameterBuffMultiplePerTurnPermil | 100 | 絶好調每好調層 +0.1(相加) |
| examConcentrationLessonValueMultiplePermil1/2 | 2000 / 2500 | **集中(ExamConcentration,官方名「強気」)分层倍率** ×2.0/×2.5 |
| examConcentrationStaminaMultiplePermil1/2 | 2000 / 2000 | 集中(強気)時**体力消耗 ×2.0** |
| examPreservationLessonValueMultiplePermil1/2 | 500 / 250 | **温存**:レッスン値 ×0.5/×0.25 |
| examPreservationStaminaMultiplePermil1/2 | 500 / 250 | 温存時体力消耗 ×0.5/×0.25 |
| examFullPowerLessonValueMultiplePermil | 3000 | **全力**:レッスン値 ×3.0 |
| fullPowerPlayableValueAdd | 1 | 全力時使用数 +1 |
| examTurnEndRecoveryStamina | 2 | **每回合结束回体力 2** |
| examLessonValueMultipleDependReviewOrAggressive(Multiple/Max)Permil | 20 / 500 | プライド:好印象/やる気每層 +2%,上限 +50% |
| examStaminaConsumptionDownPermil / AddPermil | 500 / 1000 | 消費体力減 −50% / 増 +100% |
| examGimmickParameterDebuffPermil | 667 | 不調减衰 ×0.667 |

语义修正(2026-08-16):`Concentration` 常量属**集中状态**(枚举 ExamConcentration,官方日文名「強気」,社区通称集中),非指針;温存/全力/のんびり才是指針(stance)。集中是「高输出但体力双倍消耗」的攻防权衡状态。
**对决策模型:指針+集中机制完整数值化;回合结束自动回体 2 修正体力经济学(C 层)。**

### S10 官方内置自动出牌 AI 权重表【A 数据实证,待深挖】
`ProduceExamAutoEvaluation.yaml`(66,779 行)/ `ProduceExamAutoCardSelectEvaluation.yaml`(1,049 行)= 游戏内置自动模式的评价权重:`(ExamPlayType × ProduceExamEffectType × remainingTerm) → (评价维度 → evaluation 值 + enchant 系数 permil)`。
即**官方自己的「效果 × 时机(剩余回合)」价值函数**——对 scoring.py 的终盘权重(endgame)与 play.py 出牌策略有直接参考价值,可作为校准先验或对照基线。kanon511 模拟器已直接搬用此表(枚举名原样保留,可证数据源)。

### S9 選抜試験与莉波审查链【A 数据实证】
- `ProduceExamBattleConfig`:每场考试的 turn 数+三属性审查基准+◎/△线(Bad≈Excellent×0.78,印证社区 (◯−1)×0.8)。莉波链 `p_step_audition_difficulty-hrnm` → `p_exam_battle_config-vida-03-*`(**vida=Vi>Da 型**,印证 J2 莉波広型);produce-001 Mid1 = 9 回合、基准 Vo90/Da110/Vi134(短レギュ 9T 结构与 HIF Round1 同构)。
- 選抜边界 NPC(`npc_hif_border`):produce_007 各偶像组挂载,固定分 6035 / 49806 / 136347(三次選抜晋级线,三属性 permil 平均 334/333/333,op/mid/ed 分配)。
- **待查 U7:HIF 本戦(ほしまち学園祭)的玩家侧 battleConfig/scoreConfig 具体挂哪条 id——dump 内无 `hif` 前缀 battleConfig,推测复用 contest-season 或 produce-007 系曲线,実機/数据反查待定。**

### M4 スキルカード使用数【B】
基准 **1 回合 1 张**。「スキルカード使用数追加+1」= 当回合可再出 1 张;skip 不消耗则追加 buff 可延续到下回合,一旦使用了卡残余追加即解除。另有「使用準備」(不消耗使用数直接发动)。
来源:famitsu、zutapoke 1830、note quroe_。
**对评分模型的含义:使用数追加卡的净行动成本 ≈ 0(打出它花的 1 次被它附带的 +1 抵消),当前 play_add 建模(纯加分)需重建为"免费出牌+附带效果"。**

---

## 2. 牌库动力学(章节:D1-D5)

### D1 出牌去向:逐卡由 playMovePositionType 决定【A】
本地数据实证(master 121 卡 × diff `playMovePositionType`):
- `is_lesson_once=true`(**102 张**)→ `Lost`:打出后**除外,本考试不回流**(考试结束卡组复原)
- `is_lesson_once=false`(**19 张**)→ `Grave`:打出后进捨て札,**山札抽空时重洗回流**

枚举全集:Hand / DeckFirst / DeckLast / DeckRandom / Grave / Lost / Hold(七种,ProduceDescriptionProduceCardMovePosition.yaml)。

### D2 捨て札重洗【B】
山札不足抽牌需要时,捨て札全部洗回山札,当回合继续抽满,不推迟。除外(Lost)卡不参与重洗。
来源:note nuno_1010、matomenia 638、famitsu。

### D3 「レッスン中1回」语义【B,一处社区表述冲突已裁】
= 使用后该卡进除外(Lost),同一レッスン/試験内不再入手;同名多张各自独立。考试结束后自动复原。副效应=デッキ圧縮。
再入手经验式(社区):「残りターン数 × 3 > 山札枚数」时该卡有机会再上手。
来源:matomenia 697、知恵袋 q12308041222、学マスwiki。
⚠️ 冲突裁决记录:一路调研(HIF)B8 引官方X+压缩解说博客称「lesson_once 卡用后进捨て札回流」——与本地数据(Lost 101/102)矛盾。判定:官方X说的是普通卡(Grave);压缩解说博客混淆了「删卡策略」与「lesson_once 去向」。**采纳 D1 数据裁决;残留 1% 不确定性列入実機验证清单(V2)。**

### D4 デッキ圧縮的数学本质【A+社区共识】
打出的 lesson_once 卡(池内 84%)不回流 → 有效山札持续变薄 → 非 lesson_once 循环卡(19 张,聚光灯类)与未打过的卡被抽中概率持续上升。社区压缩定义:「レッスン中1回+発動条件付き的强卡」优先拿、删无标注弱卡。
来源:本地数据 + せつP 压缩解说 + note syato_monami。

### D5 応援棒(基本卡补足)【B,修正本地表述】
P アイテム「HIF 応援棒」効果:試験開始時**山札技能卡不足 22 枚时,随机位置补入名字含「基本」的技能卡到 22 枚**;补入的基本卡不消失、破坏循环。Interval 持有 20 张(実機)正落在触发区间。
来源:学マスwiki H.I.F、game8 785450、X tenka0amayakasi。
**修正:本地旧表述「山札不足混入 HIF 応援棒卡」不准确——混入的是基本卡,応援棒是触发它的 P アイテム名。**

---

## 3. 得分公式(章节:S1-S7)——模拟器核心

### S1 回合得分总式【A 定案:官方常量 + 三个开源模拟器交叉 + 実機算例】
```
每次出牌得分 = ceil( ceil( (卡基础值 + 集中×集中分层倍率 + 好印象/やる気附加)
                          × (好調? 1.5 : 1.0) + (絶好調時 0.1×好調層) )
                    × 流行属性有效参数/100 × (1+得分上升量/100) × (不調時 0.666) )
```
逐级小数进位。実機算例(kjirou 库验证):`(23 + 4×2.0) × (1.5+0.6) = 65.10`。
交叉来源:官方 ExamSetting.yaml 常量 + kanon511(Calculator.js)/kjirou(gakumas-core,TS,带 jest+真实卡 e2e)/lts129(Gakumas-RL,function_cal.py)三实现一致;katabami83 附实测数据集(100 样本得分统计)可回归验证。仓库已存 `debug/research/repos/`(debug/ 不入库)。

### S2 好調 = ×1.5 固定【A 官方】
好調发动回合得分 ×1.5,**与剩余回合数无关**。N ターン的意义 = 覆盖 N 个出牌回合的乘区,不是价值倍数。
**官方数据实证(2026-08-16 本地 dump):`ExamSetting.yaml examParameterBuffPermil: 1500`。**
来源:Game8 609700 + 暇人雑記实机 + ExamSetting.yaml。
**对评分模型:现 log₂(N+1) 曲线形状(递减)方向正确,但语义应重写为「覆盖回合 × 0.5 增量乘区」,k_buff 留校准。**

### S3 絶好調 = 状态倍率 **+0.1×好調層(相加结构)**【A 定案,V3 关闭】
状态倍率 = 1.5 + 0.1×B(B=好調層数)——**相加**,不是连乘 1.5×(0.1B+1)。官方 `examParameterBuffMultiplePerTurnPermil: 100` + 三个模拟器实现一致 + kjirou 実機算例(1.5+0.6)。X 检证帖的「連乗」表述系笔误,中文博客相加式是对的。
语义:絶好調价值**依赖好調存量 B**(堆厚好調→点絶好調收菜)。获得:卡效果付与(池内 45 条);衰减同好調(次回合-1,付与回合保护)。
**对评分模型:`excellent_mult=2.0` 固定倍错误 → 依赖好調存量的动态倍率(上下文敏感族;中性局面按期望好調存量折算,P2 手牌跟踪后用实测)。**

### S4 集中 = 加算进基础值 × 分层倍率,一次性【A 常量+B 交叉】
消费即清空,不随回合衰减。**分层倍率(本地 dump ExamSetting):1 级 ×2.0、2 级 ×2.5**(`examConcentrationLessonValueMultiplePermil1/2: 2000/2500`;注:kanon511 仓库副本为 2000/2400/2800 三档,系旧版本,以本地 dump 为准)。即集中 N 層 → 基础值 += N×2.0(或 2.5)。「集中強化」(ExamLessonBuffMultiple)为独立乘区。连击卡每击分别代入,集中被算多遍。
来源:ExamSetting.yaml + kjirou/kanon511/lts129 三实现 + 巴哈姆特/mikalibrary。
**对评分模型:集中族从 log(turn) 曲线改为「一次性加算 × 分层倍率」语义。**

### S5 好印象 = 回合终了时按层数加算得分【B】
加算同样吃属性倍率;结算后层数 -1。等价分估算式(社区):增加数 × (剩余回合数 + 后续火力牌%合计/100)。
来源:note jolly_macaw128、mikalibrary、学マスwiki。
**对评分模型:好印象是「延时即得分族」,现归 buff log 曲线低估其终盘价值。**

### S6 属性スコアボーナス(「ビジュアル 3807%」真身)【A 数据表已找到】
每回合分配一个属性,画面 % = 该回合该属性的固有倍率,由**参数值 + 審査基準比率 + 評価档位 + 親愛度 + HIFボーナス**决定;随参数单调上升、有上限。HIF 本戦可叠到 3000%+ 级。
**官方数据实证(2026-08-16):`ProduceExamBattleScoreConfig.yaml`(4072 条)= 参数→三属性 permil 分段曲线表**。结构:同 id 按 parameter 升序 5-8 个断点,如 `parameter: 1800 → vocalPermil 21600/dancePermil 10800/visualPermil 21600`;id 家族覆盖主线六属性组合(voda/davo/…/vida)、tower、contest-season(コンテスト本戦)、選抜等。挂链:`ProduceExamBattleConfig.produceExamBattleScoreConfigId` / `ProduceStepAuditionDifficulty` / `PvpRateConfig` 三级。
**玩家侧简化规则(三模拟器一致):流行属性倍率% = 该属性有效参数/100**(実機「ビジュアル 3807%」≈ Vi 有效参数 3807,含親愛度/HIFボーナス的换算后值);BattleScoreConfig 分段表用于 **NPC 对手**。模拟器实现:玩家侧用参数/100、NPC 侧查表,两条路都不需要拟合。
来源:本地 dump + 暇人雑記/萌娘百科(机制表述)。本地「ビジュアル 3807% 含义未解」→ 已解决。

### S7 △/✕评价全体减衰【B(现象)/D(公式)】
任一属性 △ 以下时计算式改变、全体倍率减衰(実測:参数 494→770% 无✕ vs 497→686% 有✕)。精确减衰式未知。

---

## 4. 審査基準与回合分配(章节:J1-J4)

### J1 档位换算(プロ)【C+(系统检证)】
△最小値 = (◯最小値−1)×0.8(进位);◎最小値 = (◯最小値−1)×1.2;プロ基準値 = レギュラー×2;最終試験基準値 = 中間試験×3。
来源:note lal_ilul_elo(两篇检证全文)。

### J2 審査基準型比率【C+】
各偶像固定型(バランス/2極/1極/特化),◯最小値比率 40:33:27 / 45:40:15 / 50:30:20 / 60:23:17。姫崎莉波为広(Vi)>Da>Vo 型(実機 Round1 末回合 Vi 印证 J3)。

### J3 ターン属性分配【B,已有参考实现】
回合属性按審査基準比率分配;顺序随机;**最后 3 回合固定按比率从低到高,最后一回合必是最高属性**;技能卡追加的额外ターン属性与最终ターン相同。
参考实现(kanon511 `TurnType.js`+`contestData.js`):末 3 回合固定流行 3→2→1 位、第 1 回合按概率表、中段按各流行回合数随机;GvG 逐赛季的 criteria/turnTypes/firstTurn 概率数据齐全(已存 `debug/research/repos/`)。
来源:萌娘百科(全文)+ 咪卡 + kanon511。

### J4 審査基準不直接结算奖金【B】
它通过①回合属性配比、②△/✕减衰两条路径影响得分,不是「达标发奖」机制。

---

## 5. 状态效果与资源(章节:R1-R4)

### R1 buff 回合递减时机【B】
衰减名单:好調/好印象/絶好調/消費体力減増。**次回合开始时 -1;付与回合保护**(当回合新付与的 buff 下回合不减,下下回合开始才减)。集中不衰减(一次性);やる気/元気不衰减(资源池)。
来源:mikalibrary(推导演算)+ 学マスwiki(表述)。

### R2 元気 = 体力优先支付缓冲池【B】
出牌消耗时元気优先于体力扣除;部分卡元気不可代偿。体力 0 时耗体卡不可用(红字);好印象/やる気消费类仍可用。skip 消耗 1 回合回体力 2。
来源:暇人雑記、note mu_zora、4Gamer、Game8。
**对评分模型:w_energy(0.5)偏低,元気≈等值体力缓冲;C 层应加「体力不足不可用」硬约束。**

### R3 ターン追加词条【B】
存在,全游戏仅 2 张(私がスター/レジェンドスター),**均不在莉波池内**(本地 0 张一致)。「アンコール」词条不存在;正确词条:「ターン追加」「もう1回発動」「再演」。使用数追加(P アイテム付与)skip 会消失、卡付与可延续。

### R4 再演(お姉さんの感覚)【A 执行链落地】
使用後、手札有自然体の魅力≥1 则自身再使用,**4 回まで・ターン内 1 回まで・不消耗コスト**。
**执行链(2026-08-16 dump 实证)**:`enchant-p_card-01-ido-3_200-enc01` → trigger(使用後+检索计数)→ `ExamForcePlayCardSearch`(`p_card_search-target_is_self`,isSelf)→ **检索"自身"并强制再打出;再演后卡按打出流程正常进捨て札(非 Lost)**。enc02 为持续型再演状态(effectTurn -1, effectCount 2)。
実機+Game8 逐字一致。
**对评分模型:再演=一张卡多次生效+不占行动,当前 action:encore 固定值(w_cycle×3)保留,回血价值已在效果列表。**

---

## 6. HIF 本戦特有数值(章节:H1-H4)

### H1 評価点(優勝判定)【B,一处待験】
優勝判定 = R1 スコア(×1.2)+ R2 スコア;**×1.2 仅 R1 取 1 位时适用**(多数源+计算器口径;seesaawiki 摘要口径为无条件 ×1.2——**列入実機验证 V1**)。優勝目安约 111 万。順位发表画面显示含补正值,日志显示原始值。
**修正:本地 evaluation.md「R1×1.2 无条件」需修正。**

### H2 評価値(成绩等级)是另一套体系【B】
`評価値 = 参数合計×2 + スター性×7.5 + R1スコア評価(逓減,上限5500) + R2スコア評価(逓減,上限7400) − 2000`。S4+=30,000 / S5=35,000。R2 附带スター性(1.5 倍込み最大 225)。
来源:gktools HIF 計算機。

### H3 スター性【C+】
獲得系数:審査基準未達成約 1.85~2 倍、達成時 2~3 倍(上限)。獲得スコア線:1 次 14,000 / 2 次 150,000 / 3 次 390,000。

### H4 インターバル可做【B】
买技能卡(补足 22 枚最优先)、买ドリンク、P ポイント回体力、スキルカードスイッチ(编限外换卡)。R1 后強制配布 P アイテム。

### H5 本戦 scoreConfig 挂链【A 数据实证,U7 关闭】
HIF 本戦 = `Produce.yaml produce-008`(ProduceType_HatsuboshiIdolFestival,splitPairProduceId=produce-007 選抜)。
- Round1:`p_exam_battle_config-davi-01-produce_008-01`(**turn 9**)
- Round2:`p_exam_battle_config-davi-01-produce_008-02`(**turn 12**)
- 各挂同名 scoreConfig 阶梯表(parameter 0/1089/1307/1960/10000 → 三属性 permil,如 1960 → Vo 5621/Da 7069/Vi 6090)——**模拟器得分函数完全落地,零拟合**。

### H6 本戦对手:2 名具名对手对决(修正"12 人"认知)【A 数据实证】
`p_npc_group-{偶像}-produce_008-01/-02` 各 **2 名具名对手**:十王星南(jsna)为固定主对手(20 组全出现),第二名按偶像轮换;分数带:-01 组 40~41 万(jsna)/30~32 万(第二),-02 组 59~62 万。三属性 permil ~333 平均、op/mid/ed 330/330/340。**"12 人顺位"是通常試験;本戦就是 2 rival 对决**。選抜側另配 `npc_hif_border` 晋级线 NPC(固定分 6035/49806/136347)。

### H7 親愛度加成【A 数据实证】
`CharacterDearnessLevel.yaml`(等级 1-8)→ `ProduceSkill` → `ProduceEffect audition_parameter_bonus_multiple`(0050~0500 permil):**親愛度等级 → 試験参数 +5%~+50%**(produce_start 触发)。3807% 的组成之一。

### H8 メモリー/HIF ボーナス【A 数据实证】
選抜試験メモリー = `p_memory_skill-...-for_hif_memory` → 考试内 enchant(`enchant-p_ef-hif_memory-*`,效果链含全力値/参数/打牌数+1),**不是全局数值 buff**。選抜嵌入卡:`ExamContestEmbedProduceCard.yaml` 按 examEffectType 6 组 45 张候选。

### H9 指針进入/解除详细【A 数据实证】
进入:卡效果显式付与(e_effect-exam_concentration/preservation/over_preservation 等,带 1/2 档)。温存解除:元気达 5/8 阈值换 block+5 且使用数+1;のんびり:元気 10 解除→全力转档(LessonAdd+10);全力:×3.0+使用数+1。官方文本(Localization):「指針がのんびりであるため、指針を温存に変更する効果は発動しません」——指針互斥有约束。

### H10 集中(強気)层级 = 效果显式指定【A 数据实证,修正 S4 表述】
不是按集中值自动分层:`e_effect-exam_concentration-0001`(effectValue1=**1**)与 `-0002`(effectValue1=**2**)——**卡效果/GrowEffect/饮料显式给 1 级或 2 级**,倍率 ×2.0/×2.5,体力消耗均 ×2.0,PenetrateReduce 0/1。

### H11 饮料与检索位置全集【A 数据实证】
- 本戦饮料槽:`ProduceSetting produceDrinkPossessLimit: 3 / MaxLimit: 4`(実機 4 瓶=MaxLimit);无本戦专用饮料表。
- 生成卡去向:`ExamCardCreateSearch` 的 `movePositionType: Hand`——**生成卡直接进手札**。
- 检索位置枚举(ProduceCardSearch.yaml):Deck(6)/DeckAll(44)/DeckGrave(10)/Hand(11)/Hold(1)/Lost(12)/NotLost(3)/Playing(41)/RandomPool(10)/Target(140)——**DeckGrave 即「山札か捨札」**;検索条件字段含稀有度/卡ID/档位/状态/体力区间/效果组。

---

### H12 特別指導(カスタマイズ,Interval 强化环节)【A 数据实证,2026-08-16】
游戏内文本确认:「※カスタマイズは特別指導でおこなえます」(Localization)——特別指導 = カスタマイズ系统,Round1/Round2 之间的准备环节(及変卡流程?)对技能卡强化。
- **选项表**:`ProduceCardCustomize.yaml` 340 条,每条 = P 点消耗(producePoint 20/40/100)+ 指导次数档(customizeCount 1/2/3)+ **注入 grow effect**(`g_effect-*`)。两种强化:数值提升链(如 block_add 4→13)与新增效果(cost_reduce/aggressive_add 等)。
- **挂载**:`ProduceCard.produceCardCustomizeIds` + `maxCustomizeCount`;**流派池 170 卡中 98 张可被特別指導**(アイドル魂 max1/2 选项、ファーストステップ+ max3/3 选项等)。
- `ProduceCardCustomizeRarityEvaluation`:定制后稀有度评价。
- **对项目**:①Interval 的特別指導决策(选卡+选项)是 Round2 流程的开发点,管线未覆盖;②定制效果全为 grow effect,评分层 GROW_EFFECT_TAGS 五族映射已覆盖——评「定制后价值增量」可零新开发;③実機変卡流程第三步的「训练师选项」疑似同一系统,待実機对照。

---

## 7. 社区策略共识(非硬机制,校准锚)

### P1 引擎卡为什么强(四条,全部对应评分修正方向)【B 共识】
① 使用数追加系(アイドル魂等)打出不亏行动次数;② 抽卡系(聚光灯等)提升 key 卡到手率;③ 再演一张多次生效不耗成本;④ 国民的アイドル让收尾卡翻倍(もう1回発動)。

### P2 ガラクタロード莉波定番流程【B 共识】
序盤早出お姉さんの感覚(定再演次数)→ 追加ドロー/使用数+1 把自然体の魅力抽上手 → 再演 4 回回体力 → 终盘 国民的アイドル → 自然体の魅力收尾。**自然体の魅力 = 体力の 1000% 分パラメータ上升(按当時体力,使用卡每张 +14)——是"レッスン用参数卡",不进考试得分乘区。**

### P3 Interval 策略【B 共识】
R1 只 9 回合场整不起来 → 绝对必要卡+使用数付き压缩卡以外极力争不拿;最优先补到 22 枚以上;其次补センブリソーダ/ブーストエキス;好調依赖卡 R1 容易腐烂。

### P4 定番编成(game8 汇总,校准锚)【B】
センス轴:存在感/シュプレヒコール/スポットライト/話題沸騰 + 国民的アイドル/至高のエンタメ;サポカ 4-2-0/4-1-1(参数上限高)。

### P5 压缩流分歧【C】
共识:压缩仍是核心思想,22 枚下限惩罚过度压缩;4 枚循环轴 vs キセキ轴有流派分歧。

---

## 8. 未查明清单(模拟器拟合/実機验证项)

| # | 项 | 状态 | 建议路径 |
| --- | --- | --- | --- |
| ~~U1~~ | ~~参数→スコアボーナス%映射~~ **已关闭(2026-08-16 dump)** | `ProduceExamBattleScoreConfig.yaml` 4072 条分段曲线(5-8 断点/条),查表+插值 | — |
| U2 | 3807% 成分分解(親愛度/HIFボーナス占比) | 未查明 | 実機 |
| U3 | △/✕减衰精确式 | 仅现象(Bad≈Ex×0.78 数据印证) | 実機或客户端逻辑 |
| ~~V3~~ | ~~絶好調乘区结构~~ **已关闭(2026-08-16)** | **相加 1.5+0.1B 定案**:官方 100‰ + kanon511/kjirou/lts129 三实现一致 + kjirou 実機算例 | — |
| ~~U5~~ | ~~手札硬上限~~ **已关闭(ExamSetting)** | handLimit 5 / turnStartDistribute 3 / holdLimit 2 | — |
| V1 | ×1.2 是否仅限 R1 第 1 位 | `PvpRateConfig.examBattleFirstRankBonusPermil: 200` 印证 1 位限定形态;HIF 本戦字段待确认 | 実機(看 R1 非 1 位时的順位画面) |
| V2 | lesson_once 用后不可回流(D1 裁决) | 数据裁决,1% 残留 | 実機(Round 中卡组计数变化) |
| U6 | 審査基準別精确ターン配比数字 | seesaawiki 正文 403;J3 规则(末 3 回合低→高)已 B | 换网重抓或実機记录 |
| ~~U7~~ | ~~HIF 本戦玩家侧 scoreConfig 挂链~~ **已关闭(2026-08-16 dump)** | `p_exam_battle_config-davi-01-produce_008-01`(R1,turn9)/`-02`(R2,turn12)+ 同名阶梯表,见 H5 | — |
| U8 | スター性获得公式(1.85~3 倍系数) | 仅客户端,dump 无表;只有 StarPermilUp 效果类型 | 実機采样或放弃(低影响:不关系决策只关系等级) |
| U9 | 体力/元気上限基础值 | 仅客户端(実機 HUD 可读 34) | 実機 |

---

## 9. 对评分模型/模拟器的影响映射(修正清单)

| 依据条目 | 修正对象 | 内容 |
| --- | --- | --- |
| S2 | scoring buff 族 | 好調语义重写:覆盖回合 ×0.5 乘区;log 曲线保留作近似,k_buff 校准 |
| S3 | scoring 绝好调 | excellent_mult 固定 2.0 → 依赖好調存量 B 的动态倍率(系数 0.1 已官方) |
| S4 | scoring 集中 | 一次性加算语义(线性),非 log(turn) |
| S5 | scoring 好印象 | 延时即得分族:层数 ×(剩余回合+火力%)终盘权重 |
| M4/P1① | scoring play_add | 重建模为「净零成本出牌」:不再按 w_cycle 加分,改为抵消本卡行动成本 |
| D1/D3/D4 | scoring 新增 | lesson_once(Lost)压缩收益项;Grave 循环卡=可重复使用价值×次数;join 产物补 playMovePositionType 字段 |
| R2 | scoring C 层 | 元気→体力缓冲(w_energy 调高);体力不足不可用硬约束 |
| H1 | evaluation.md | ×1.2 条件修正 |
| S6/U1 | simulator | 属性倍率=最大拟合项,実機取样建表 |
| M3/D1/D2/M4 | simulator | 牌库引擎规格:每回合抽3→出牌(1+追加)→按卡 playMovePositionType 分流 Grave/Lost→山札空重洗 Grave |

---

## 10. 主要来源

- 本地:実機日志(session-20260815.jsonl、finals-daily-log)、gakumasu-diff 数据 dump(ExamSetting/ProduceExamBattleScoreConfig/ProduceExamBattleConfig/ProduceExamAutoEvaluation 等机制表,裁决依据)
- **参考实现仓库(2026-08-16 调研,已存 `debug/research/repos/`,debug/ 不入库)**:[kanon511/new_gakumas_contest_simulator](https://github.com/kanon511/new_gakumas_contest_simulator)(最完整 GvG 模拟器,Calculator/TurnType/官方AI权重搬用)、[kjirou/gakumas-core](https://github.com/kjirou/gakumas-core)(TS 内部处理复现库,jest+e2e,実機算例)、[lts129/Gakumas-RL](https://github.com/lts129/Gakumas-RL)(中文 RL 环境,同公式)、[katabami83/gakumas_contest_simulator](https://github.com/katabami83/gakumas_contest_simulator)(附 100 样本实测数据集)、[tyuukiti/gakumasu-calc](https://github.com/tyuukiti/gakumasu-calc)(**含 `Data/Plans/hif.yaml` 完整 HIF 日程数据**)、[zliu-aki/simple_gakuen_idolmaster](https://github.com/zliu-aki/simple_gakuen_idolmaster)(effect 串解析)。**无公开客户端 Il2Cpp dump 结果仓库**(仅 dump 工具:dhlrunner/Gakumas_mod、vertesan/nitidus)
- 官方/准官方:[famitsu ルール解説](https://app.famitsu.com/20240513_2227423/)、[公式X 不具合公告](https://x.com/gkmas_official/status/1914545259524297099)、[公式X 教えてあさり先生](https://x.com/gkmas_official/status/1795726772459192332)、[4Gamer](https://www.4gamer.net/games/778/G077853/20240531038/)
- 攻略站:[Game8 609700/609737/783836/785450 等](https://game8.jp/gakuen-idolmaster/)、[学マスwiki(seesaawiki)](https://seesaawiki.jp/gakumasu/)、[gamerch 855850](https://gamerch.com/gakumasu/855850)、[wikiwiki HIF](https://wikiwiki.jp/gakumas/HIF/%E5%9F%BA%E6%9C%AC%E6%83%85%E5%A0%B1)
- 社区检证:[note lal_ilul_elo 審査基準](https://note.com/lal_ilul_elo/n/ndc72ead428c6)、[mikalibrary](https://mikalibrary.com/posts/life/gakumas_aplus/)、[matomenia 638/697/640](https://matomenia.site/638)、[zutapoke 1830](https://zutapoke.com/1830/)、[暇人雑記](https://www.himajin-block30.com/entry/2024/06/05/231349)、[kokorogu](https://kokorogu.com/gakumasu-garakuta1)、[せつP 压缩解说](https://www.setandset.com/archives/gakmascompression.html)
- 计算机:[gakumas-final-score](https://gakumas-final-score.netlify.app/)、[gktools HIF](https://gktools.ris.moe/calculator/hif)
