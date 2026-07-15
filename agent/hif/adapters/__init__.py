"""HIF 出牌适配层（把画面像素翻译成 ExamState）。

唯一接触 maafw Context 的层（通过 OcrPort 协议抽象）：
- card_dict:   OCR 卡名词典生成 + 好调卡判定
- exam_reader: ExamStateReader 协调 YOLO+OCR 读取，组装 ExamState
- state_reconciliation: 重启重扫与同局已验证账本的纯逻辑对账

设计：纯逻辑组装函数（build_hand_summary/build_exam_state）与 maafw 调用分离，
单测注入 mock OcrPort 即可离线验证组装逻辑。
"""
