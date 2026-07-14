from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path
from importlib import import_module


def _load_action_module():
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        return import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)


def _journal(records):
    return SimpleNamespace(
        capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
        record=lambda *args, **kwargs: records.append((args, kwargs)),
    )


def test_safe_advance_stops_when_the_changed_frame_is_not_a_known_hif_target(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFSafeAdvanceAuto()
    action.ACTION_DELAY = 0
    records = []
    stop_reasons = []
    clicks = []

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(
        module,
        "get_runtime_hif_session",
        lambda: SimpleNamespace(safe_advance_count=0, record_safe_advance=lambda fingerprint: True, reset_safe_advance=lambda: None),
    )
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_detect_screen_profile", lambda context, image: None)
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append((list(box), double)) or True)
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )
    screenshots = iter((b"before", b"unknown"))

    assert action.run(object(), SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert clicks == [([341, 204, 0, 3], False)]
    assert stop_reasons == [("unknown_hif_transition", "safe_advance_next_page_not_confirmed")]
    assert records[-1][0][1:3] == ("safe_advance", "unverified")


def test_schedule_direct_transition_stops_when_the_target_page_is_unknown(monkeypatch):
    module = _load_action_module()
    action = module.ProduceChooseHIFEventAuto()
    action.ACTION_DELAY = 0
    action._configure_page_execution(SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    records = []
    stop_reasons = []
    clicks = []
    screenshots = iter((b"unknown"))

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: False)
    monkeypatch.setattr(action, "_detect_screen_profile", lambda context, image: None)
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append((list(box), double)) or True)
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )

    assert action._execute_event(object(), b"before", {"name": "差し入れ", "box": [100, 100, 40, 40]})
    assert clicks == [([100, 100, 40, 40], False)]
    assert stop_reasons == [("finals_action_select", "schedule_first_click_next_page_not_confirmed")]
    assert records[-1][0][1:3] == ("select_schedule", "unverified")


def test_schedule_confirmation_stops_when_the_target_page_is_unknown(monkeypatch):
    module = _load_action_module()
    action = module.ProduceChooseHIFEventAuto()
    action.ACTION_DELAY = 0
    action._configure_page_execution(SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    records = []
    stop_reasons = []
    clicks = []
    screenshots = iter((b"selected", b"unknown"))

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: image == b"selected")
    monkeypatch.setattr(action, "_detect_screen_profile", lambda context, image: None)
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append((list(box), double)) or True)
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )

    assert action._execute_event(object(), b"before", {"name": "差し入れ", "box": [100, 100, 40, 40]})
    assert clicks == [([100, 100, 40, 40], False), ([100, 100, 40, 40], False)]
    assert stop_reasons == [("finals_action_select", "schedule_confirm_next_page_not_confirmed")]
    assert records[-1][0][1:3] == ("confirm_schedule", "unverified")


def test_source_confirmation_never_rehydrates_a_missing_target_from_action_parameters(monkeypatch):
    module = _load_action_module()
    module.reset_runtime_hif_session()
    action = module.ProduceChooseHIFSelectChangeSourceAuto()
    records = []
    stop_reasons = []
    confirmations = []

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"source-deck")
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen_id: image)
    monkeypatch.setattr(action, "_confirm_source_card_change", lambda *args, **kwargs: confirmations.append((args, kwargs)) or True)
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )

    assert action.run(
        object(),
        SimpleNamespace(
            custom_action_param=(
                '{"preset_id":"rinami_good_condition_safe","execution_mode":"single_step",'
                '"source_deck_probe":"confirm_source_card","source_card_name":"大胆不敵",'
                '"selected_target_name":"成就","explicit_source_authorized":true}'
            )
        ),
    )
    assert confirmations == []
    assert stop_reasons == [("select_change_source_deck", "selected_target_card_missing_or_invalid")]


def test_drink_overflow_keep_requires_explicit_single_step_permission(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDrinkOverflowObserve()
    records = []
    stop_reasons = []

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"overflow")
    monkeypatch.setattr(action, "_keep_black_vinegar", lambda *args: (_ for _ in ()).throw(AssertionError("观察模式不得进入资源选择")))
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )

    assert action.run(
        object(),
        SimpleNamespace(custom_action_param='{"drink_overflow_keep":"初星黒酢"}'),
    )
    assert stop_reasons == [("drink_overflow", "page_execution_mode_not_single_step")]
    assert records[-1][0][1:3] == ("resolve_drink_overflow", "observed")


def test_public_lesson_result_stops_when_a_changed_frame_has_no_known_target(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFPublicLessonResultAuto()
    action.ACTION_DELAY = 0
    records = []
    stop_reasons = []
    clicks = []
    screenshots = iter((b"before", b"unknown"))

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: image == b"before")
    monkeypatch.setattr(action, "_detect_confirmed_hif_transition", lambda context, image: None)
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append((list(box), double)) or True)
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )

    assert action.run(object(), SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert clicks == [([341, 204, 0, 3], False)]
    assert stop_reasons == [("public_lesson_result", "public_lesson_result_next_page_not_confirmed")]
    assert records[-1][0][1:3] == ("advance_public_lesson_result", "unverified")


def test_start_produce_stops_when_the_confirmation_disappears_without_a_known_target(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFStartProduceAuto()
    action.ACTION_DELAY = 0
    records = []
    stop_reasons = []
    clicks = []
    screenshots = iter((b"before", b"unknown"))

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: image == b"before")
    monkeypatch.setattr(action, "_detect_confirmed_hif_transition", lambda context, image: None)
    monkeypatch.setattr(
        action,
        "_find_text_option",
        lambda context, image, phrases, roi: SimpleNamespace(hit=True, best_result=SimpleNamespace(box=[210, 1030, 300, 105])),
    )
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append((list(box), double)) or True)
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )

    assert action.run(object(), SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert clicks == [([210, 1030, 300, 105], False)]
    assert stop_reasons == [("hif_start_confirm", "start_next_page_not_confirmed")]
    assert records[-1][0][1:3] == ("start_produce", "unverified")


def test_card_single_step_never_claims_a_supported_postcondition_before_round_validation_exists(monkeypatch):
    module = _load_action_module()
    from agent.hif.decisions.state import ActionKind, CardAction

    action = module.ProduceCardsHIF()
    records = []
    approvals = []
    tasks = []
    observation = SimpleNamespace(
        state=SimpleNamespace(oneesan_used=False, natural_finisher_used=False),
        detections=[SimpleNamespace(card_name="自然体の魅力", box=(100, 700, 120, 180))],
        missing_fields=(),
        screen_confidence=1.0,
    )
    reader = SimpleNamespace(read_exam_observation=lambda *args: observation)
    session = SimpleNamespace(card_was_played=lambda *args: False, record_card=lambda *args: None)

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(module, "get_runtime_hif_session", lambda: session)
    monkeypatch.setattr(module.ExamStateReader, "from_context", classmethod(lambda cls, context: reader))
    monkeypatch.setattr(
        module,
        "GarakutaRinamiStrategy",
        lambda payload: SimpleNamespace(decide=lambda state: CardAction(ActionKind.PLAY_CARD, "自然体の魅力", "test")),
    )
    monkeypatch.setattr(
        module,
        "load_hif_roi_calibration",
        lambda: SimpleNamespace(is_exam_execution_ready=True, device_id="test", updated_at="test"),
    )

    def approve(mode, **kwargs):
        approvals.append(kwargs)
        return SimpleNamespace(should_execute=False, reason="postcondition_not_supported")

    monkeypatch.setattr(module, "approve_card_execution", approve)
    monkeypatch.setattr(action, "_get_screenshot", lambda context: SimpleNamespace(size=(720, 1280)))
    monkeypatch.setattr(action, "_get_health", lambda context, image: None)
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不得出牌")))
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(
        context,
        SimpleNamespace(custom_action_param='{"preset_id":"rinami_good_condition_safe","round":"round1","execution_mode":"single_step"}'),
    )
    assert approvals and approvals[0]["postcondition_supported"] is False
    assert tasks == ["ProduceHIFUnknownStop"]
    assert records[-2][1]["details"]["reason"] == "postcondition_not_supported"


def test_live_skip_mode_is_safe_stop_until_a_target_page_postcondition_is_calibrated(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFLiveObserve()
    records = []
    stop_reasons = []

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"live")
    monkeypatch.setattr(action, "_click_box_with_verification", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不得快进")))
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )

    assert action.run(
        object(),
        SimpleNamespace(custom_action_param='{"execution_mode":"single_step","live_mode":"skip_once"}'),
    )
    assert stop_reasons == [("live", "live_skip_execution_not_supported")]
    assert records[-1][0][1:3] == ("skip_live", "observed")


def test_memory_photo_next_stops_when_the_changed_frame_is_not_the_confirm_page(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFMemoryPhotoNext()
    action.ACTION_DELAY = 0
    records = []
    stop_reasons = []
    screenshots = iter((b"before", b"unknown"))

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(
        action,
        "_find_text_option",
        lambda *args: SimpleNamespace(best_result=SimpleNamespace(text="次へ", box=[240, 1120, 242, 82])),
    )
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: True)
    monkeypatch.setattr(action, "_detect_confirmed_hif_transition", lambda context, image: None)
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )

    assert action.run(object(), SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert stop_reasons == [("memory_photo_select", "photo_next_next_page_not_confirmed")]
    assert records[-1][0][1:3] == ("photo_next", "unverified")
