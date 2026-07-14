from __future__ import annotations

import re
import json
import struct
import hashlib
from types import SimpleNamespace
from pathlib import Path

import pytest

from agent.hif import reward_pages
from agent.hif.observation import observe_hif_page
from agent.hif.screen_profiles import load_hif_screen_profiles

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "assets" / "data" / "hif" / "pipeline_coverage.json"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _image_size(path: Path) -> tuple[int, int]:
    """只读解析 PNG/JPEG 头，避免把 Pillow 作为 CI 必需依赖。"""

    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if not data.startswith(b"\xff\xd8"):
        raise ValueError(f"不支持的 HIF 夹具格式: {path}")
    offset = 2
    while offset + 9 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        length = int.from_bytes(data[offset : offset + 2], "big")
        if marker in {*range(0xC0, 0xC4), *range(0xC5, 0xC8), *range(0xC9, 0xCC), *range(0xCD, 0xD0)}:
            return int.from_bytes(data[offset + 5 : offset + 7], "big"), int.from_bytes(data[offset + 3 : offset + 5], "big")
        offset += length
    raise ValueError(f"无法读取 JPEG 尺寸: {path}")


class _ReplayOCRContext:
    """以夹具清单的已审阅文本重放 OCR 适配器；不把该测试称为 Maa OCR E2E。"""

    def __init__(self, texts: list[str]):
        self._texts = texts

    def run_recognition(self, name, image, pipeline_override):
        del image
        expected = pipeline_override[name]["expected"]
        patterns = expected if isinstance(expected, list) else [expected]
        text = next(
            (
                candidate
                for candidate in self._texts
                if any(re.search(pattern, candidate) for pattern in patterns)
            ),
            "",
        )
        return SimpleNamespace(
            hit=bool(text),
            best_result=SimpleNamespace(text=text, box=(100, 500, 300, 48)) if text else None,
        )


def test_real_frame_fixture_manifest_is_minimal_and_has_unique_ids_and_files():
    manifest = _manifest()
    fixtures = manifest["fixtures"]

    assert manifest["fixture_policy"]["frame_size"] == [720, 1280]
    assert len(fixtures) == 9
    assert len({fixture["id"] for fixture in fixtures}) == len(fixtures)
    assert len({fixture["file"] for fixture in fixtures}) == len(fixtures)
    assert all(fixture["file"].startswith("tests/fixtures/hif/frames/") for fixture in fixtures)
    assert all(fixture["game_state_data"] is True for fixture in fixtures)
    assert all("debug/" not in fixture["file"] for fixture in fixtures)


@pytest.mark.parametrize("fixture", _manifest()["fixtures"], ids=lambda item: item["id"])
def test_real_frame_fixture_preserves_raw_frame_contract_and_declared_rois(fixture):
    image_path = ROOT / fixture["file"]
    profile = load_hif_screen_profiles().get(fixture["screen_id"])

    assert image_path.is_file()
    assert profile is not None
    assert image_path.stat().st_size > 1024
    assert hashlib.sha256(image_path.read_bytes()).hexdigest() == fixture["sha256"]
    width, height = _image_size(image_path)
    assert (width, height) == (720, 1280)
    for region_name in fixture["regions"]:
        x, y, region_width, region_height = profile.regions[region_name]
        assert 0 <= x < width and 0 <= y < height
        assert x + region_width <= width and y + region_height <= height


@pytest.mark.parametrize("fixture", _manifest()["fixtures"], ids=lambda item: item["id"])
def test_real_frame_fixture_replays_a_unique_reviewed_page_contract(fixture):
    profile = load_hif_screen_profiles().get(fixture["screen_id"])
    assert profile is not None

    detector = fixture["detector"]
    image_path = ROOT / fixture["file"]
    image = image_path.read_bytes()
    if detector == "drink_reward_selected":
        result = reward_pages.detect_drink_reward_page(_ReplayOCRContext(fixture["adapter_texts"]), image)
        assert result == reward_pages.HIFDrinkRewardPageMatch("selected_detail", fixture["expected_name"], (100, 500, 300, 48))
    elif detector == "skill_reward_selected":
        result = reward_pages.detect_skill_reward_selected_page(_ReplayOCRContext(fixture["adapter_texts"]), image)
        assert result == reward_pages.HIFSkillRewardPageMatch(fixture["expected_name"], (100, 500, 300, 48))
    elif detector == "skill_reward_reveal":
        result = reward_pages.detect_skill_reward_reveal_page(_ReplayOCRContext(fixture["adapter_texts"]), image)
        assert result == reward_pages.HIFSkillRewardPageMatch(fixture["expected_name"], (100, 500, 300, 48))
    else:
        observation = observe_hif_page(fixture["adapter_texts"])
        assert observation.is_unique
        assert observation.screen_id == fixture["screen_id"]
        assert observation.screen_id not in fixture["rejects"]

    for rejected_screen in fixture["rejects"]:
        rejected_profile = load_hif_screen_profiles().get(rejected_screen)
        assert rejected_profile is not None
        assert not rejected_profile.matches(tuple(fixture["adapter_texts"]))
