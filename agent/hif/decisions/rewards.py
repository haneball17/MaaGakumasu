"""HIF 三选一奖励的效果文本关键词评分（変卡目标/技能卡/P 饮料共用）。

输入是点选候选后详情面板的效果文本（纯白底深色字，实机实录可 OCR），
评分表来自 assets/data/hif/decision_keywords.json，按培育倾向分组。

匹配规则：
- 长词优先、负面词先行、命中即从文本移除，避免子串重复计分（絶好調/好調、集中消費/集中）
- 全/半角括号内的条件说明文案不计分（実機 2026-08-15：「パラメータ+30（好調効果を2倍適用）」
  的括号内 好調 曾误计 6 分）
- 含正则元字符的关键词按正则匹配（好調[0-9０-９]*ターン 句式，防「好調状態の場合」类条件词误中）

覆盖链（grill 定案）：GUI 输入（custom_action_param）> decision_override.json 文件 > 倾向基准。
点名覆盖：只改点名的参数，未点名项保持所选倾向基准值。
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from dataclasses import field, dataclass

from loguru import logger

DATA_PATH = Path(__file__).resolve().parents[3] / "assets" / "data" / "hif" / "decision_keywords.json"
OVERRIDE_PATH = Path(__file__).resolve().parents[3] / "assets" / "data" / "hif" / "decision_override.json"

_REGEX_META = set(".+*?[](){}|^$\\")
_BRACKET_PATTERNS = (re.compile(r"（[^）]*）"), re.compile(r"\([^)]*\)"))


def _is_regex(keyword: str) -> bool:
    return any(ch in _REGEX_META for ch in keyword)


def _strip_brackets(text: str) -> str:
    """剔除全/半角括号内的条件说明文案（不计分）。"""
    for pattern in _BRACKET_PATTERNS:
        text = pattern.sub("◇", text)
    return text


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

    def score_detail(self, text: str) -> tuple[float, list[tuple[str, float]]]:
        """评分并返回 (总分, 命中明细 [(关键词, 分值)])。

        顺序：变体归一 → 括号条件剔除 → 负面词（长词先行）→ 正面词；
        命中即从剩余文本移除，防子串重复计分。
        """
        remaining = _strip_brackets(self.normalize(text))
        breakdown: list[tuple[str, float]] = []
        total = 0.0
        for words in (self.negative, self.positive):
            for keyword in sorted(words, key=len, reverse=True):
                hits = 0
                if _is_regex(keyword):
                    while re.search(keyword, remaining):
                        remaining = re.sub(keyword, "◇", remaining, count=1)
                        hits += 1
                else:
                    while keyword in remaining:
                        remaining = remaining.replace(keyword, "◇", 1)
                        hits += 1
                if hits:
                    value = words[keyword]
                    total += hits * value
                    breakdown.append((keyword, hits * value))
        return total, breakdown

    def score(self, text: str) -> float:
        """按关键词评分效果文本（明细见 score_detail）。"""
        return self.score_detail(text)[0]

    def accepts(self, score: float) -> bool:
        """最高分达到阈值才接受本屏候选，否则考虑再抽。"""
        return score >= self.accept_threshold


def _filter_numeric(mapping: dict, table_keys: set[str], source: str) -> dict[str, float]:
    """数值覆盖容错：非数值/未知关键词忽略并警告（grill 定案：部分生效）。"""
    filtered: dict[str, float] = {}
    for key, value in mapping.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            logger.warning(f"HIF 决策覆盖: {source} 中 {key!r} 非数值,忽略")
            continue
        if table_keys and key not in table_keys:
            logger.warning(f"HIF 决策覆盖: {source} 中 {key!r} 不在关键词表,忽略")
            continue
        filtered[key] = float(value)
    return filtered


def _apply_overrides(tables: dict[str, KeywordTable], overrides: dict, source: str) -> None:
    """把一份覆盖（文件或 GUI）合并进全部倾向表（点名覆盖，原地改）。"""
    if not overrides:
        return
    for name, table in tables.items():
        table_pos = dict(table.positive)
        table_neg = dict(table.negative)
        pos_over = _filter_numeric(overrides.get("keyword_weights", {}), set(table_pos), source)
        neg_over = _filter_numeric(overrides.get("negative_weights", {}), set(table_neg), source)
        table_pos.update(pos_over)
        table_neg.update(neg_over)
        threshold = overrides.get("accept_threshold")
        new_threshold = table.accept_threshold
        if isinstance(threshold, (int, float)) and not isinstance(threshold, bool) and threshold > 0:
            new_threshold = float(threshold)
        tables[name] = KeywordTable(
            preference=name,
            positive=table_pos,
            negative=table_neg,
            accept_threshold=new_threshold,
            ocr_variants=table.ocr_variants,
        )


def load_file_overrides(path: Path = OVERRIDE_PATH) -> dict:
    """读 decision_override.json（`_` 前缀键为说明忽略）；文件缺失/语法错返回空并警告。"""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        logger.warning(f"HIF 决策覆盖: {path.name} JSON 语法错误,整体忽略 ({err})")
        return {}
    if not isinstance(payload, dict):
        logger.warning(f"HIF 决策覆盖: {path.name} 非对象,整体忽略")
        return {}
    return {k: v for k, v in payload.items() if not k.startswith("_")}


def load_keyword_tables(
    path: Path = DATA_PATH,
    overrides: dict | None = None,
) -> dict[str, KeywordTable]:
    """加载评分表并应用覆盖链（点名覆盖语义，三倾向统一生效）。

    overrides 是调用方已合并好的覆盖（GUI > 文件）；None 时自动读文件覆盖。
    """
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

    merged: dict = {}
    for source in (load_file_overrides(), overrides or {}):
        for key, value in source.items():
            if isinstance(value, dict):
                merged.setdefault(key, {}).update(value)
            else:
                merged[key] = value
    if merged:
        _apply_overrides(tables, merged, "覆盖")
    return tables


def pick_best_candidate(scored: list[tuple[str, float]]) -> tuple[str, float] | None:
    """从 (候选标签, 分数) 列表选最高分；并列取先出现者。"""

    if not scored:
        return None
    return max(scored, key=lambda item: item[1])
