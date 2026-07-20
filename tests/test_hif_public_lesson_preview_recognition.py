import sys
from types import SimpleNamespace
from pathlib import Path
from importlib import import_module


def _load_recognition_module():
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        return import_module("agent.custom.reco.hif")
    finally:
        sys.path.remove(agent_path)


def _result(hit, text=""):
    return SimpleNamespace(hit=hit, best_result=SimpleNamespace(text=text))


def test_public_lesson_preview_recognition_returns_native_detail_for_selected_da():
    recognition = _load_recognition_module().HIFPublicLessonPreviewDetail()
    values = {
        "HIFPublicLessonPreviewSelected": _result(True),
        "HIFPublicLessonPreviewStamina": _result(True, "-8"),
        "HIFPublicLessonPreviewStar": _result(True, "+30"),
        "HIFPublicLessonPreviewVo": _result(False),
        "HIFPublicLessonPreviewDa": _result(True, "+120"),
        "HIFPublicLessonPreviewVi": _result(True, "+20"),
    }
    context = SimpleNamespace(run_recognition=lambda name, image, pipeline_override: values[name])
    argv = SimpleNamespace(custom_recognition_param='{"candidate":"Da"}', image=object())

    result = recognition.analyze(context, argv)

    assert result.box == [0, 0, 1, 1]
    assert result.detail == {
        "candidate": "Da",
        "stamina": -8,
        "star": 30,
        "vo": 0,
        "da": 120,
        "vi": 20,
        "verified": True,
    }


def test_public_lesson_preview_recognition_logs_the_native_detail_on_success(monkeypatch):
    module = _load_recognition_module()
    messages = []
    monkeypatch.setattr(module, "logger", SimpleNamespace(info=messages.append))
    recognition = module.HIFPublicLessonPreviewDetail()
    values = {
        "HIFPublicLessonPreviewSelected": _result(True),
        "HIFPublicLessonPreviewStamina": _result(True, "-8"),
        "HIFPublicLessonPreviewStar": _result(True, "+30"),
        "HIFPublicLessonPreviewVo": _result(False),
        "HIFPublicLessonPreviewDa": _result(True, "+120"),
        "HIFPublicLessonPreviewVi": _result(True, "+20"),
    }

    recognition.analyze(
        SimpleNamespace(run_recognition=lambda name, image, pipeline_override: values[name]),
        SimpleNamespace(custom_recognition_param='{"candidate":"Da"}', image=object()),
    )

    assert messages == ["HIF 公开课预览: {'candidate': 'Da', 'stamina': -8, 'star': 30, 'vo': 0, 'da': 120, 'vi': 20, 'verified': True}"]


def test_public_lesson_preview_recognition_refuses_an_unselected_candidate():
    recognition = _load_recognition_module().HIFPublicLessonPreviewDetail()
    context = SimpleNamespace(run_recognition=lambda name, image, pipeline_override: _result(False))
    argv = SimpleNamespace(custom_recognition_param='{"candidate":"Vo"}', image=object())

    result = recognition.analyze(context, argv)

    assert result.box is None
    assert result.detail == {"candidate": "Vo", "verified": False, "reason": "candidate_not_selected"}


def test_public_lesson_preview_recognition_accepts_selected_color_when_select_ocr_is_truncated():
    recognition = _load_recognition_module().HIFPublicLessonPreviewDetail()
    values = {
        "HIFPublicLessonPreviewSelected": _result(False),
        "HIFPublicLessonPreviewSelectedColor": _result(True),
        "HIFPublicLessonPreviewStamina": _result(True, "-6"),
        "HIFPublicLessonPreviewStar": _result(True, "+20"),
        "HIFPublicLessonPreviewVo": _result(True, "+110"),
        "HIFPublicLessonPreviewDa": _result(False),
        "HIFPublicLessonPreviewVi": _result(True, "+10"),
    }
    context = SimpleNamespace(run_recognition=lambda name, image, pipeline_override: values[name])
    argv = SimpleNamespace(custom_recognition_param='{"candidate":"Vo"}', image=object())

    result = recognition.analyze(context, argv)

    assert result.detail == {
        "candidate": "Vo",
        "stamina": -6,
        "star": 20,
        "vo": 110,
        "da": 0,
        "vi": 10,
        "verified": True,
    }


def test_public_lesson_preview_requires_an_unselected_page_before_clicking_any_course():
    recognition = _load_recognition_module().HIFPublicLessonPreviewNoSelection()
    values = {
        "HIFPublicLessonPreviewVoSelectedColor": _result(False),
        "HIFPublicLessonPreviewDaSelectedColor": _result(True),
    }
    context = SimpleNamespace(run_recognition=lambda name, image, pipeline_override: values[name])

    result = recognition.analyze(context, SimpleNamespace(image=object()))

    assert result.box is None
    assert result.detail == {"verified": False, "reason": "Da_already_selected"}
