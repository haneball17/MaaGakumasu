import sys
from types import SimpleNamespace
from pathlib import Path
from importlib import import_module

import numpy as np


def _load_recognition_module():
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        return import_module("agent.custom.reco.hif")
    finally:
        sys.path.remove(agent_path)


def _result(hit, text=""):
    return SimpleNamespace(hit=hit, best_result=SimpleNamespace(text=text))


def _context(values):
    return SimpleNamespace(run_recognition=lambda name, image, pipeline_override: values.get(name, _result(False)))


def _preview_values(*, candidate="Da", stamina="-8", star="+30", vo="+20", da="+120", vi=None):
    values = {
        "HIFPublicLessonPreviewSelected": _result(True),
        "HIFPublicLessonPreviewStamina": _result(True, stamina),
        "HIFPublicLessonPreviewVoBonus": _result(True, "32.1%"),
        "HIFPublicLessonPreviewDaBonus": _result(True, "54.9%"),
        "HIFPublicLessonPreviewViBonus": _result(True, "43.0%"),
    }
    for attribute, value in {"star": star, "vo": vo, "da": da, "vi": vi}.items():
        key = attribute.title()
        values[f"HIFPublicLessonPreview{key}Present"] = _result(value is not None)
        if value is not None:
            values[f"HIFPublicLessonPreview{key}"] = _result(True, value)
    return values


def test_public_lesson_preview_recognition_returns_native_detail_for_selected_da():
    recognition = _load_recognition_module().HIFPublicLessonPreviewDetail()
    values = _preview_values()
    context = _context(values)
    argv = SimpleNamespace(custom_recognition_param='{"candidate":"Da"}', image=object())

    result = recognition.analyze(context, argv)

    assert result.box == [0, 0, 1, 1]
    assert result.detail == {
        "candidate": "Da",
        "stamina": -8,
        "star": 30,
        "vo": 20,
        "da": 120,
        "vi": 0,
        "bonus_per_mille": {"vo": 321, "da": 549, "vi": 430},
        "final_gain": {"star": 30, "vo": 26, "da": 185, "vi": 0},
        "verified": True,
    }


def test_public_lesson_preview_recognition_accepts_unsigned_stamina_cost():
    recognition = _load_recognition_module().HIFPublicLessonPreviewDetail()

    result = recognition.analyze(
        _context(_preview_values(stamina="8")),
        SimpleNamespace(custom_recognition_param='{"candidate":"Da"}', image=object()),
    )

    assert result.box == [0, 0, 1, 1]
    assert result.detail["stamina"] == -8


def test_public_lesson_preview_recognition_treats_blank_vo_slot_as_zero_in_vi_preview():
    recognition = _load_recognition_module().HIFPublicLessonPreviewDetail()
    values = _preview_values(candidate="Vi", stamina="8", star="+30", vo=None, da="+20", vi="+120")

    def run_recognition(name, image, pipeline_override):
        if name == "HIFPublicLessonPreviewVoPresent":
            return _result(pipeline_override[name]["method"] == 6)
        return values.get(name, _result(False))

    result = recognition.analyze(
        SimpleNamespace(run_recognition=run_recognition),
        SimpleNamespace(custom_recognition_param='{"candidate":"Vi"}', image=object()),
    )

    assert result.box == [0, 0, 1, 1]
    assert result.detail["candidate"] == "Vi"
    assert result.detail["vo"] == 0
    assert result.detail["da"] == 20
    assert result.detail["vi"] == 120


def test_public_lesson_preview_recognition_keeps_star_when_its_orange_border_is_sparse():
    recognition = _load_recognition_module().HIFPublicLessonPreviewDetail()
    values = _preview_values()

    def run_recognition(name, image, pipeline_override):
        if name == "HIFPublicLessonPreviewStarPresent":
            param = pipeline_override[name]
            return _result(param["lower"][0] == 0 and param["count"] == 5)
        return values.get(name, _result(False))

    result = recognition.analyze(
        SimpleNamespace(run_recognition=run_recognition),
        SimpleNamespace(custom_recognition_param='{"candidate":"Da"}', image=object()),
    )

    assert result.box == [0, 0, 1, 1]
    assert result.detail["star"] == 30


def test_public_lesson_preview_recognition_retries_split_da_bonus_on_an_upscaled_crop():
    recognition = _load_recognition_module().HIFPublicLessonPreviewDetail()
    values = _preview_values(candidate="Vi", stamina="8", star="+30", vo=None, da="+20", vi="+120")

    def run_recognition(name, image, pipeline_override):
        if name == "HIFPublicLessonPreviewDaBonus":
            return _result(image.shape[1] == 240, "54.9%")
        return values.get(name, _result(False))

    result = recognition.analyze(
        SimpleNamespace(run_recognition=run_recognition),
        SimpleNamespace(custom_recognition_param='{"candidate":"Vi"}', image=np.zeros((1280, 720, 3), dtype=np.uint8)),
    )

    assert result.box == [0, 0, 1, 1]
    assert result.detail["bonus_per_mille"]["da"] == 549


def test_public_lesson_preview_recognition_logs_the_native_detail_on_success(monkeypatch):
    module = _load_recognition_module()
    messages = []
    monkeypatch.setattr(module, "logger", SimpleNamespace(info=messages.append))
    recognition = module.HIFPublicLessonPreviewDetail()
    values = _preview_values()

    recognition.analyze(
        _context(values),
        SimpleNamespace(custom_recognition_param='{"candidate":"Da"}', image=object()),
    )

    assert messages == [
        "HIF 公开课预览: {'candidate': 'Da', 'stamina': -8, 'star': 30, 'vo': 20, 'da': 120, 'vi': 0, "
        "'bonus_per_mille': {'vo': 321, 'da': 549, 'vi': 430}, 'final_gain': {'star': 30, 'vo': 26, 'da': 185, 'vi': 0}, 'verified': True}"
    ]


def test_public_lesson_preview_recognition_refuses_an_unselected_candidate():
    recognition = _load_recognition_module().HIFPublicLessonPreviewDetail()
    context = SimpleNamespace(run_recognition=lambda name, image, pipeline_override: _result(False))
    argv = SimpleNamespace(custom_recognition_param='{"candidate":"Vo"}', image=object())

    result = recognition.analyze(context, argv)

    assert result.box is None
    assert result.detail == {"candidate": "Vo", "verified": False, "reason": "candidate_not_selected"}


def test_public_lesson_preview_recognition_refuses_selected_color_without_select_ocr():
    recognition = _load_recognition_module().HIFPublicLessonPreviewDetail()
    values = _preview_values(candidate="Vo", stamina="-6", star="+20", vo="+110", da=None, vi="+10")
    values["HIFPublicLessonPreviewSelected"] = _result(False)
    values["HIFPublicLessonPreviewSelectedColor"] = _result(True)
    context = _context(values)
    argv = SimpleNamespace(custom_recognition_param='{"candidate":"Vo"}', image=object())

    result = recognition.analyze(context, argv)

    assert result.box is None
    assert result.detail == {"candidate": "Vo", "verified": False, "reason": "candidate_not_selected"}


def test_public_lesson_preview_allows_unselected_yellow_vi_card():
    recognition = _load_recognition_module().HIFPublicLessonPreviewNoSelection()
    values = {
        "HIFPublicLessonPreviewSelected": _result(False),
        "HIFPublicLessonPreviewViSelectedColor": _result(True),
    }
    context = _context(values)

    result = recognition.analyze(context, SimpleNamespace(image=object()))

    assert result.box == [0, 0, 1, 1]
    assert result.detail == {"verified": True}


def test_public_lesson_pending_decision_does_not_require_da_to_be_selected(monkeypatch):
    module = _load_recognition_module()
    recognition = module.HIFPublicLessonPendingDecision()
    pending = SimpleNamespace(day_remaining=5, candidate_id="Da")
    monkeypatch.setattr(module, "get_runtime_hif_session", lambda: SimpleNamespace(pending_public_lesson=pending))

    result = recognition.analyze(SimpleNamespace(), SimpleNamespace(image=object()))

    assert result.box == [0, 0, 1, 1]
    assert result.detail == {"candidate": "Da", "verified": True}
