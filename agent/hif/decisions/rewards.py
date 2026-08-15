"""HIF 三选一奖励的效果文本关键词评分（変卡目标/技能卡/P 饮料共用）。

输入是点选候选后详情面板的效果文本（纯白底深色字，实机实录可 OCR），
评分表来自 assets/data/hif/decision_keywords.json，按培育倾向分组。
匹配规则：长词优先、负面词先行、命中即从文本移除，
避免子串重复计分（絶好調/好調、集中消費/集中）。
"""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import field, dataclass

DATA_PATH = Path(__file__).resolve().parents[3] / "assets" / "data" / "hif" / "decision_keywords.json"


@dataclass(frozen=True, slots=True)
class KeywordTable:
    """单一倾向的关键词评分表。"""

    preference: str
    positive: dict[str, float]
    negative: dict[str, float]
    accept_threshold: float
    ocr_variants: dict[str, str] = field(default_factory=dict)

    def normalize(self, text: str) -> str:
        """OCR 误识变体归一，先于评分执行。"""
        for variant, canonical in self.ocr_variants.items():
            if variant in text:
                text = text.replace(variant, canonical)
        return text

    def score(self, text: str) -> float:
        """按关键词评分效果文本；命中即移除，负面长词先行。"""
        remaining = self.normalize(text)
        total = 0.0
        for words in (self.negative, self.positive):
            for keyword in sorted(words, key=len, reverse=True):
                while keyword in remaining:
                    total += words[keyword]
                    remaining = remaining.replace(keyword, "◇", 1)
        return total

    def accepts(self, score: float) -> bool:
        """最高分达到阈值才接受本屏候选，否则考虑再抽。"""
        return score >= self.accept_threshold


def load_keyword_tables(path: Path = DATA_PATH) -> dict[str, KeywordTable]:
    """加载数据文件中的全部倾向评分表，键为倾向名。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    variants = payload.get("ocr_variants", {})
    threshold = float(payload.get("accept_threshold", 4))
    tables: dict[str, KeywordTable] = {}
    for preference, spec in payload["preferences"].items():
        tables[preference] = KeywordTable(
            preference=preference,
            positive={k: float(v) for k, v in spec["positive"].items()},
            negative={k: float(v) for k, v in spec["negative"].items()},
            accept_threshold=threshold,
            ocr_variants=dict(variants),
        )
    return tables


def pick_best_candidate(scored: list[tuple[str, float]]) -> tuple[str, float] | None:
    """从 (候选标签, 分数) 列表选最高分；并列取先出现者。"""

    if not scored:
        return None
    return max(scored, key=lambda item: item[1])
