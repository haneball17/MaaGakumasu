"""HIF 出牌决策包。

从原 Maa-gakumas-bot 仓库移植的纯逻辑决策层（零 maafw 依赖）：
- state:     ExamState/HandSummary/CardAction 等数据结构
- config:    ProfilePayload 角色配置参数（ガラクタロード阈值）
- hand_meta: 卡名→消耗 查表（assets/data/hif/skill_cards.json）
- play:      GarakutaRinamiStrategy 再演压缩流启发式（7 条分支）

适配层（ExamStateReader）从画面读状态后调用 play.GarakutaRinamiStrategy.decide()。
"""
