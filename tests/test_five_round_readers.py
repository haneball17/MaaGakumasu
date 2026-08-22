"""五轮验证読取件单测（2026-08-22）：名称匹配三件套 / P item 分段 / 牌堆分段 /
R1-R2 两位数锚消歧 / Round1Play 参数化 / P 饮料槽 raw 退路。

全部纯逻辑离线可跑；実機 probe 纪律（≥3 跨画面时点）由阶段 2 実機覆盖。
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "agent"))

from agent.hif.decisions.state import ExamRound  # noqa: E402
from agent.hif.decisions.scoring import (  # noqa: E402
    _load_all_drinks,
    match_drink_name,
    match_pitem_name,
    _load_pitem_effects,
)
from agent.custom.action.produce_hif import ProduceHIFRound1Play  # noqa: E402

# ---------------------------------------------------------------- 名称匹配


class TestMatchPitemName:
    def test_exact_hit(self) -> None:
        pool = _load_pitem_effects()
        if not pool:  # 数据文件缺失时跳过（降级可用语义）
            pytest.skip("pitem_effects.json missing")
        name = next(iter(pool))
        got, record = match_pitem_name(name)
        assert got == name
        assert record and record.get("name") == name

    def test_truncated_prefix_matches(self) -> None:
        pool = _load_pitem_effects()
        if not pool:
            pytest.skip("pitem_effects.json missing")
        name = next(iter(pool))
        got, _ = match_pitem_name(name[: max(3, len(name) - 3)])
        assert got == name

    def test_garbage_returns_none(self) -> None:
        got, record = match_pitem_name("あいうえおかきく")
        assert got is None and record is None

    def test_empty_input(self) -> None:
        got, record = match_pitem_name(" 　")
        assert got is None and record is None


class TestMatchDrinkName:
    def test_exact_and_fuzzy(self) -> None:
        pool = _load_all_drinks()
        if not pool:
            pytest.skip("drinks.json missing")
        assert match_drink_name("初星水")[0] == "初星水"
        # NFKC/空白容错
        assert match_drink_name(" 初星水 ")[0] == "初星水"

    def test_miss(self) -> None:
        got, record = match_drink_name("存在しない飲料XYZ")
        assert got is None and record is None


# ---------------------------------------------------------------- P item 弹窗分段


class TestSegmentPitemWords:
    def test_two_items_segmented_by_name_rows(self) -> None:
        # 実機 pitem2_detail.png OCR 词行结构（简化）
        words = [
            {"text": "好調が8ターン以上の場合、", "y": 56, "h": 26},
            {"text": "ルカードを4回使用するごとに、", "y": 90, "h": 30},
            {"text": "想定外のチケット", "y": 354, "h": 28},
            {"text": "ビジュアルターンなら、ターン開始後、", "y": 454, "h": 27},
        ]
        items = ProduceHIFRound1Play._segment_pitem_words(words)
        assert len(items) == 2
        named = [i for i in items if i["name"]]
        assert len(named) == 1
        assert named[0]["name"] == "想定外のチケット"
        assert len(named[0]["ocr_lines"]) == 1  # 后续效果行归属名字段
        unnamed = [i for i in items if not i["name"]]
        assert len(unnamed) == 1 and len(unnamed[0]["ocr_lines"]) >= 2  # 无名段保留原文

    def test_all_noise_dropped(self) -> None:
        words = [{"text": "単発ノイズ", "y": 10, "h": 20}]
        assert ProduceHIFRound1Play._segment_pitem_words(words) == []


# ---------------------------------------------------------------- 牌堆分段


class TestSegmentPileLines:
    def test_anchor_segmentation(self) -> None:
        lines = ["お姉さんの感覚", "山札", "自然体の魅力+", "国民的アイドル", "捨て札", "好調状態の提唱", "除外", "円満解決プラン"]
        deck = ProduceHIFRound1Play._segment_pile_lines(lines)
        # 锚前 head 与山札锚后的行都归 draw；<4 字卡名（大声援类）会被噪声过滤
        assert deck["draw"] == ["お姉さんの感覚", "自然体の魅力+", "国民的アイドル"]
        assert deck["discard"] == ["好調状態の提唱"]
        assert deck["exclude"] == ["円満解決プラン"]
        assert deck["hand"] == []

    def test_noise_lines_dropped(self) -> None:
        deck = ProduceHIFRound1Play._segment_pile_lines(["12", "D", "山札", "好調状態の提唱"])
        assert deck["draw"] == ["好調状態の提唱"]

    def test_head_without_anchor_goes_draw(self) -> None:
        deck = ProduceHIFRound1Play._segment_pile_lines(["タイミングの基本", "捨て札", "パンプアップ"])
        assert deck["draw"] == ["タイミングの基本"]
        assert deck["discard"] == ["パンプアップ"]


# ---------------------------------------------------------------- R1/R2 锚消歧（两位数 regex）

class TestRoundAnchorDisambiguation:
    @pytest.mark.parametrize("text,expect", [
        ("12", True), ("11", True), ("10", True),
        ("9", False), ("1", False), ("21", False), ("13", False),
        ("残りターン", False),
    ])
    def test_two_digit_regex(self, text: str, expect: bool) -> None:
        import re
        assert bool(re.search(r"1[0-2]", text)) is expect


# ---------------------------------------------------------------- Round1Play 参数化


class FakeRunArg:
    def __init__(self, param_json: str):
        self.custom_action_param = param_json


class TestRoundConfig:
    def test_default_r1(self) -> None:
        total, rnd, tag = ProduceHIFRound1Play._round_config(FakeRunArg(json.dumps({"round1_mode": "play"})))
        assert (total, rnd, tag) == (9, ExamRound.HONSEN_R1, "round1")

    def test_r2_param(self) -> None:
        total, rnd, tag = ProduceHIFRound1Play._round_config(FakeRunArg(
            json.dumps({"round1_mode": "play", "total_turns": 12, "round": "r2", "round_tag": "round2"})))
        assert (total, rnd, tag) == (12, ExamRound.HONSEN_R2, "round2")

    def test_null_param_string(self) -> None:
        # MaaFW 对未定义 param 传 "null" 字符串
        total, rnd, tag = ProduceHIFRound1Play._round_config(FakeRunArg("null"))
        assert (total, rnd, tag) == (9, ExamRound.HONSEN_R1, "round1")

    def test_bad_json(self) -> None:
        total, _, _ = ProduceHIFRound1Play._round_config(FakeRunArg("{broken"))
        assert total == 9


# ---------------------------------------------------------------- P 饮料槽


class TestAvailableDrinksFallback:
    def test_raw_fallback_when_unmatched(self) -> None:
        slots = [
            {"slot": 1, "raw": "未知飲料X", "name": None},
            {"slot": 2, "raw": None, "name": None},
            {"slot": 3, "raw": "初星水", "name": "初星水"},
        ]
        assert ProduceHIFRound1Play._available_drinks_from_slots(slots) == ["未知飲料X", "初星水"]


# ---------------------------------------------------------------- ExamState 新字段

class TestExamStateResourceFields:
    def test_defaults_empty(self) -> None:
        from agent.hif.decisions.state import ExamState, HandSummary
        st = ExamState(
            round=ExamRound.HONSEN_R1, turn=1, total_turns=9, current_flow="Vi",
            good_condition_turns=0, focus=0, stamina=30,
            hand=HandSummary(
                has_shizen_no_miryoku=False, has_oneesan_no_kankaku=False,
                has_kokuminteki_idol=False, good_condition_card_count=0,
                swap_hand_available=False, draw_available=False,
            ),
            reprise_count=0, cards_played=0, deck_size=22,
            oneesan_used=False, natural_finisher_used=False,
            available_p_drinks=[],
        )
        assert st.p_items == [] and st.p_drinks == [] and st.deck == {}


# ---------------------------------------------------------------- 変卡牌库整屏判底


class TestDeckScanFullScreenBottom:
    """判底纯逻辑（模拟逐屏 entries 序列,断言不再跳过新屏二三排——実機 2026-08-22 bug）。"""

    @staticmethod
    def _sim_screens(screens: list[list[str]]) -> list[str]:
        """模拟 _scan_full_deck 收集:每屏 12 格(name 空串=漏读),整屏重复即停,
        返回去重清单(还原扫描循环核心,不跑 maafw)。"""
        entries: list[tuple[int, str]] = []
        for screen, names in enumerate(screens):
            for n in names:
                entries.append((screen, n))
            if screen > 0:
                cur = [n for s, n in entries if s == screen and n]
                prior = {n for s, n in entries if s < screen and n}
                if cur and all(n in prior for n in cur):
                    break
        seen, out = set(), []
        for _, n in entries:
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        return out

    def test_overlap_row_not_misjudged_bottom(self) -> None:
        # 26 张:屏1 [A-L 12张], 屏2 [K L M-V 重叠2+新10], 屏3 [U V 整屏重复=到底]
        s1 = [f"卡{i:02d}" for i in range(12)]                     # A..L
        s2 = s1[10:] + [f"新{i:02d}" for i in range(10)]            # K L + 新00..新09
        s3 = [f"新{i:02d}" for i in range(9, -1, -1)]               # 全部已见
        got = self._sim_screens([s1, s2, s3])
        assert len(got) == 22  # 12 + 10 新,重叠不重计;旧探针版会在屏 2 就断底只收 12

    def test_all_new_screens_continue(self) -> None:
        s1 = [f"a{i}" for i in range(12)]
        s2 = [f"b{i}" for i in range(12)]
        got = self._sim_screens([s1, s2])
        assert len(got) == 24

    def test_dedupe_keeps_first(self) -> None:
        from agent.custom.action.produce_hif import ProduceChooseHIFSelectChangeSourceAuto
        entries = [
            {"name": "お姉さんの感覚", "cell": "x"},
            {"name": "お姉さんの感覚", "cell": "y"},
            {"name": "", "cell": "z"},
            {"name": "自然体の魅力", "cell": "w"},
        ]
        got = ProduceChooseHIFSelectChangeSourceAuto._dedupe_deck(entries)
        assert [e["name"] for e in got] == ["お姉さんの感覚", "自然体の魅力"]


# ---------------------------------------------------------------- GuardedTap 指纹


class TestGuardedTapFingerprint:
    def test_fingerprint_stable_and_sensitive(self) -> None:
        import numpy as np

        from agent.custom.action.produce_hif import _ProduceHIFActionBase
        base = np.zeros((1280, 720, 3), dtype=np.uint8)
        base[100:200, 100:200] = 255
        same = base.copy()
        changed = base.copy()
        changed[500:600, 400:500] = 200
        fp1 = _ProduceHIFActionBase._fingerprint(base)
        assert fp1 and fp1 == _ProduceHIFActionBase._fingerprint(same)
        assert fp1 != _ProduceHIFActionBase._fingerprint(changed)


# ---------------------------------------------------------------- 灰卡判定（用户 UI 约束 2026-08-22）


class TestGrayCardDetection:
    def test_gray_card_detected(self) -> None:
        import numpy as np
        from agent.custom.action.produce_hif import ProduceHIFRound1Play
        img = np.full((60, 400, 3), 120, dtype=np.uint8)  # 纯灰:饱和度 0(BGR 同值)
        assert ProduceHIFRound1Play._is_gray_card(img, (10, 5, 80, 120)) is True

    def test_colored_card_passes(self) -> None:
        import numpy as np
        from agent.custom.action.produce_hif import ProduceHIFRound1Play
        img = np.zeros((60, 400, 3), dtype=np.uint8)
        img[..., 0] = 200  # B 高
        img[..., 2] = 40   # R 低 → 高饱和(BGR)
        assert ProduceHIFRound1Play._is_gray_card(img, (10, 5, 80, 120)) is False

    def test_band_saturation_pure(self) -> None:
        import numpy as np
        from agent.custom.action.produce_hif import ProduceHIFRound1Play
        gray = np.full((4, 8, 3), 100, dtype=np.uint8)
        color = np.zeros((4, 8, 3), dtype=np.uint8)
        color[..., 0] = 220
        assert ProduceHIFRound1Play._band_saturation(gray) < 5
        assert ProduceHIFRound1Play._band_saturation(color) > 180
