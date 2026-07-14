from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path
from importlib import import_module

import pytest

from agent.hif import reward_pages


def _load_hif_recognition_module():
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        return import_module("agent.custom.reco.hif")
    finally:
        sys.path.remove(agent_path)


def _hit(box=(1, 2, 3, 4)):
    return SimpleNamespace(hit=True, best_result=SimpleNamespace(box=box))


def _miss():
    return SimpleNamespace(hit=False, best_result=None)


def test_drink_reward_page_matcher_accepts_the_prompt_state(monkeypatch):
    calls = []

    def fake_ocr(context, image, name, expected, roi):
        del context, image, roi
        calls.append((name, expected))
        return _hit((5, 6, 7, 8)) if name == "ProduceRecognitionHIFDrinkRewardPrompt" else _miss()

    monkeypatch.setattr(reward_pages, "_run_ocr", fake_ocr)

    match = reward_pages.detect_drink_reward_page(SimpleNamespace(), object())

    assert match == reward_pages.HIFDrinkRewardPageMatch("prompt", None, (5, 6, 7, 8))
    assert len(calls) == 1
    assert calls[0][0] == "ProduceRecognitionHIFDrinkRewardPrompt"


def test_drink_reward_page_matcher_requires_a_known_detail_and_receive_button(monkeypatch):
    catalog = SimpleNamespace(drink_names=("初星黒酢", "パワフル漢方ドリンク"))

    def fake_ocr(context, image, name, expected, roi):
        del context, image, roi
        if name == "ProduceRecognitionHIFDrinkRewardPrompt":
            return _miss()
        if name == "ProduceRecognitionHIFDrinkRewardReceive":
            return _hit((230, 1052, 260, 84))
        if "初星黒酢" in expected[0]:
            return _hit((220, 506, 280, 42))
        return _miss()

    monkeypatch.setattr(reward_pages, "_run_ocr", fake_ocr)
    monkeypatch.setattr(reward_pages, "load_hif_catalog", lambda: catalog)

    match = reward_pages.detect_drink_reward_page(SimpleNamespace(), object())

    assert match == reward_pages.HIFDrinkRewardPageMatch("selected_detail", "初星黒酢", (220, 506, 280, 42))


def test_drink_reward_page_matcher_rejects_a_receive_button_without_a_known_drink(monkeypatch):
    catalog = SimpleNamespace(drink_names=("初星黒酢",))

    def fake_ocr(context, image, name, expected, roi):
        del context, image, expected, roi
        return _hit() if name == "ProduceRecognitionHIFDrinkRewardReceive" else _miss()

    monkeypatch.setattr(reward_pages, "_run_ocr", fake_ocr)
    monkeypatch.setattr(reward_pages, "load_hif_catalog", lambda: catalog)

    assert reward_pages.detect_drink_reward_page(SimpleNamespace(), object()) is None


def test_drink_reward_reveal_matcher_requires_the_known_name_in_the_result_banner(monkeypatch):
    catalog = SimpleNamespace(drink_names=("初星黒酢", "パワフル漢方ドリンク"))

    def fake_ocr(context, image, name, expected, roi):
        del context, image, roi
        if name == "ProduceRecognitionHIFDrinkRewardRevealReceive":
            return _hit((230, 1052, 260, 84))
        if name == "ProduceRecognitionHIFDrinkRewardRevealName" and "パワフル漢方ドリンク" in expected[0]:
            return _hit((153, 850, 412, 44))
        return _miss()

    monkeypatch.setattr(reward_pages, "_run_ocr", fake_ocr)
    monkeypatch.setattr(reward_pages, "load_hif_catalog", lambda: catalog)

    match = reward_pages.detect_drink_reward_reveal_page(SimpleNamespace(), object())

    assert match == reward_pages.HIFDrinkRewardPageMatch("reveal", "パワフル漢方ドリンク", (153, 850, 412, 44))


def test_skill_reward_selected_page_requires_both_known_card_name_and_receive_button(monkeypatch):
    catalog = SimpleNamespace(skill_names=("意地", "基本の基本"))

    def fake_ocr(context, image, name, expected, roi):
        del context, image, roi
        if name == "ProduceRecognitionHIFSkillRewardReceive":
            return _hit((230, 1052, 260, 84))
        if name == "ProduceRecognitionHIFSkillRewardKnownDetail" and any("意地" in pattern for pattern in expected):
            return SimpleNamespace(hit=True, best_result=SimpleNamespace(box=(188, 505, 345, 52), text="意地"))
        return _miss()

    monkeypatch.setattr(reward_pages, "_run_ocr", fake_ocr)
    monkeypatch.setattr(reward_pages, "load_hif_catalog", lambda: catalog)

    match = reward_pages.detect_skill_reward_selected_page(SimpleNamespace(), object())

    assert match == reward_pages.HIFSkillRewardPageMatch("意地", (188, 505, 345, 52))


def test_skill_reward_selected_page_rejects_receive_button_without_a_known_card(monkeypatch):
    catalog = SimpleNamespace(skill_names=("意地",))

    def fake_ocr(context, image, name, expected, roi):
        del context, image, expected, roi
        return _hit((230, 1052, 260, 84)) if name == "ProduceRecognitionHIFSkillRewardReceive" else _miss()

    monkeypatch.setattr(reward_pages, "_run_ocr", fake_ocr)
    monkeypatch.setattr(reward_pages, "load_hif_catalog", lambda: catalog)

    assert reward_pages.detect_skill_reward_selected_page(SimpleNamespace(), object()) is None


def test_skill_reward_reveal_page_requires_the_known_card_name_in_the_result_banner(monkeypatch):
    catalog = SimpleNamespace(skill_names=("意地", "祝福"))

    def fake_ocr(context, image, name, expected, roi):
        del context, image, roi
        if name == "ProduceRecognitionHIFSkillRewardRevealReceive":
            return _hit((230, 1052, 260, 84))
        if name == "ProduceRecognitionHIFSkillRewardRevealName" and "祝福" in expected[0]:
            return SimpleNamespace(hit=True, best_result=SimpleNamespace(box=(326, 850, 68, 44), text="祝福"))
        return _miss()

    monkeypatch.setattr(reward_pages, "_run_ocr", fake_ocr)
    monkeypatch.setattr(reward_pages, "load_hif_catalog", lambda: catalog)

    match = reward_pages.detect_skill_reward_reveal_page(SimpleNamespace(), object())

    assert match == reward_pages.HIFSkillRewardPageMatch("祝福", (326, 850, 68, 44))


@pytest.mark.parametrize(
    ("class_name", "detector_name", "match", "detail_key", "expected_name"),
    (
        ("ProduceHIFDrinkRewardPage", "detect_drink_reward_page", reward_pages.HIFDrinkRewardPageMatch("selected_detail", "初星黒酢", (1, 2, 3, 4)), "drink_name", "初星黒酢"),
        ("ProduceHIFDrinkRewardRevealPage", "detect_drink_reward_reveal_page", reward_pages.HIFDrinkRewardPageMatch("reveal", "初星黒酢", None), "drink_name", "初星黒酢"),
        ("ProduceHIFSkillRewardSelectedPage", "detect_skill_reward_selected_page", reward_pages.HIFSkillRewardPageMatch("トークタイム", (5, 6, 7, 8)), "skill_name", "トークタイム"),
        ("ProduceHIFSkillRewardRevealPage", "detect_skill_reward_reveal_page", reward_pages.HIFSkillRewardPageMatch("祝福", None), "skill_name", "祝福"),
    ),
)
def test_custom_reward_recognitions_preserve_match_box_and_detail_contract(monkeypatch, class_name, detector_name, match, detail_key, expected_name):
    hif = _load_hif_recognition_module()

    monkeypatch.setattr(hif, detector_name, lambda context, image: match)
    result = getattr(hif, class_name)().analyze(SimpleNamespace(), SimpleNamespace(image=object()))

    assert result.box == (list(match.box) if match.box else [0, 0, 1, 1])
    assert result.detail[detail_key] == expected_name


@pytest.mark.parametrize(
    ("class_name", "detector_name"),
    (
        ("ProduceHIFDrinkRewardPage", "detect_drink_reward_page"),
        ("ProduceHIFDrinkRewardRevealPage", "detect_drink_reward_reveal_page"),
        ("ProduceHIFSkillRewardSelectedPage", "detect_skill_reward_selected_page"),
        ("ProduceHIFSkillRewardRevealPage", "detect_skill_reward_reveal_page"),
    ),
)
def test_custom_reward_recognitions_return_no_box_for_an_unconfirmed_page(monkeypatch, class_name, detector_name):
    hif = _load_hif_recognition_module()

    monkeypatch.setattr(hif, detector_name, lambda context, image: None)
    result = getattr(hif, class_name)().analyze(SimpleNamespace(), SimpleNamespace(image=object()))

    assert result.box is None
    assert result.detail["detail"].startswith("未确认")
