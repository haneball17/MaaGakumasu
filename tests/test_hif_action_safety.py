from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path
from importlib import import_module

import pytest

from agent.hif.domain import HIFPublicLessonPreview
from agent.hif.session import HIFRunSession


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


def _public_lesson_preview(candidate: str) -> HIFPublicLessonPreview:
    return HIFPublicLessonPreview(
        candidate,
        -8,
        30,
        {"vo": 120 if candidate == "Vo" else 20 if candidate == "Da" else 0, "da": 120 if candidate == "Da" else 20, "vi": 120 if candidate == "Vi" else 0},
        {"vo": 321, "da": 549, "vi": 430},
        {"star": 30, "vo": 158 if candidate == "Vo" else 26 if candidate == "Da" else 0, "da": 185 if candidate == "Da" else 30, "vi": 171 if candidate == "Vi" else 0},
        True,
    )


def _public_lesson_reading():
    return SimpleNamespace(
        state=SimpleNamespace(day_remaining=5),
        page_observation=SimpleNamespace(is_unique=True, screen_id="finals_prepare"),
    )


def test_public_lesson_browse_stops_after_vi_without_reselecting_da(monkeypatch):
    module = _load_action_module()
    action = module.ProduceBrowseHIFPublicLessonAuto()
    session = HIFRunSession()
    selected = []
    previews = {candidate: _public_lesson_preview(candidate) for candidate in ("Vo", "Da", "Vi")}

    monkeypatch.setattr(module, "get_runtime_hif_session", lambda: session)
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"initial")
    monkeypatch.setattr(module.HIFStateReader, "from_context", lambda context, image: SimpleNamespace(read_finals_prepare_state=_public_lesson_reading))
    monkeypatch.setattr(action, "_is_unselected", lambda context, image: True)
    monkeypatch.setattr(action, "_select_and_read", lambda context, image, candidate, **kwargs: (candidate.encode(), selected.append(candidate) or previews[candidate]))

    assert action.run(object(), SimpleNamespace(custom_action_param='{"public_lesson_action":"browse_fixed_da_test"}'))

    assert selected == ["Vo", "Da", "Vi"]
    assert session.pending_public_lesson is not None
    assert session.pending_public_lesson.candidate_id == "Da"


def test_public_lesson_execute_restores_da_from_vi_then_submits(monkeypatch):
    module = _load_action_module()
    action = module.ProduceExecuteHIFPublicLessonAuto()
    action.ACTION_DELAY = 0
    session = HIFRunSession()
    previews = tuple(_public_lesson_preview(candidate) for candidate in ("Vo", "Da", "Vi"))
    session.set_pending_public_lesson("Da", 5, previews)
    clicks, records, tasks = [], [], []
    screenshots = iter((b"da", b"result"))

    monkeypatch.setattr(module, "get_runtime_hif_session", lambda: session)
    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"vi")
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda context, screen_state: next(screenshots))
    monkeypatch.setattr(module.HIFStateReader, "from_context", lambda context, image: SimpleNamespace(read_finals_prepare_state=_public_lesson_reading))
    monkeypatch.setattr(action, "_is_candidate_selected", lambda context, image, candidate: False)
    monkeypatch.setattr(action, "_read_preview", lambda context, image, candidate: previews[1])
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append(list(box)) or True)
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)
    context = SimpleNamespace(run_recognition=lambda name, image: SimpleNamespace(hit=True), run_task=lambda task: tasks.append(task))

    assert action.run(context, SimpleNamespace(custom_action_param='{"public_lesson_action":"execute_pending_test"}'))

    assert clicks == [[360, 1000, 1, 1], [360, 1000, 1, 1]]
    assert session.pending_public_lesson is None
    assert tasks == []


def test_public_lesson_execute_submits_once_when_da_is_already_selected(monkeypatch):
    module = _load_action_module()
    action = module.ProduceExecuteHIFPublicLessonAuto()
    action.ACTION_DELAY = 0
    session = HIFRunSession()
    previews = tuple(_public_lesson_preview(candidate) for candidate in ("Vo", "Da", "Vi"))
    session.set_pending_public_lesson("Da", 5, previews)
    clicks, tasks = [], []

    monkeypatch.setattr(module, "get_runtime_hif_session", lambda: session)
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"da")
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda context, screen_state: b"result")
    monkeypatch.setattr(module.HIFStateReader, "from_context", lambda context, image: SimpleNamespace(read_finals_prepare_state=_public_lesson_reading))
    monkeypatch.setattr(action, "_is_candidate_selected", lambda context, image, candidate: True)
    monkeypatch.setattr(action, "_read_preview", lambda context, image, candidate: previews[1])
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append(list(box)) or True)
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)
    context = SimpleNamespace(run_recognition=lambda name, image: SimpleNamespace(hit=True), run_task=lambda task: tasks.append(task))

    assert action.run(context, SimpleNamespace(custom_action_param='{"public_lesson_action":"execute_pending_test"}'))

    assert clicks == [[360, 1000, 1, 1]]
    assert session.pending_public_lesson is None
    assert tasks == []


def test_source_deck_yolo_slot_assignment_never_turns_an_empty_slot_into_the_previous_card():
    module = _load_action_module()
    action = module.ProduceChooseHIFSelectChangeSourceAuto()
    slots = action._visible_source_slots()
    # 实机末行只有三张卡；r3c4 的详情会保留 r3c3，故不能由详情文字反推占用。
    results = [
        SimpleNamespace(box=[roi[0] + 18, roi[1] + 18, 82, 82], score=0.91)
        for slot_id, roi in slots
        if slot_id != "visible_slot_r3c4"
    ]
    results.append(SimpleNamespace(box=[370, 100, 130, 130], score=0.99))  # 顶部对比卡，网格外。

    occupied = action._source_deck_occupied_slots_from_results(results, slots)

    assert len(occupied) == 11
    assert "visible_slot_r3c3" in occupied
    assert "visible_slot_r3c4" not in occupied


def test_day1_change_pair_stops_at_the_visible_change_confirmation(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1SelectChangePair()
    records = []
    stop_reasons = []
    target = {"target_name": "始まりの合図", "slot": "candidate_center", "slot_roi": [297, 837, 127, 128]}
    source = {"matched_name": "大胆不敵", "effect_texts": ("効果",), "name_confidence": 0.99, "effect_confidence": 0.99}
    source_slot = module.HIFSelectChangeSlot(
        slot_id="visible_slot_r1c2",
        slot_roi=(227, 638, 120, 120),
        name="大胆不敵",
        confidence=0.99,
        frame_fingerprint="source",
        page_index=0,
    )

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda context, screen_id: b"target")
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen_id: image)
    def enumerate_targets(context, image):
        action._remember_pair_target_snapshot([target])
        return [target], b"target-enumerated"

    monkeypatch.setattr(action, "_enumerate_pair_targets", enumerate_targets)
    monkeypatch.setattr(
        action,
        "_select_pair_target",
        lambda context, image, slot_id, slot_roi, expected_target_name=None: (
            target,
            b"target-selected",
            SimpleNamespace(),
            SimpleNamespace(),
        ),
    )
    monkeypatch.setattr(action, "_advance_pair_to_source", lambda context, image, selected: b"source")
    def browse_source_deck(context, image):
        page = module.HIFSelectChangePage(page_index=0, signature=((source_slot.slot_id, source_slot.name),), slots=(source_slot,))
        module.get_runtime_hif_session().set_select_change_source_snapshot((source_slot,), (page,))
        return b"source-browse-end"

    monkeypatch.setattr(action, "_browse_full_pair_source_deck", browse_source_deck)
    monkeypatch.setattr(action, "_cancel_pair_source_deck", lambda context, image: b"target-after-cancel")
    monkeypatch.setattr(action, "_replay_pair_source_page", lambda context, image, slot: (source, b"source-selected"))
    monkeypatch.setattr(action, "_result_anchor_confirmed", lambda context, image: True)
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen, reason: stop_reasons.append((screen, reason)) or True)

    assert action.run(
        object(),
        SimpleNamespace(custom_action_param='{"execution_mode":"single_step","temporary_target_name":"始まりの合図","temporary_source_name":"大胆不敵"}'),
    )
    assert stop_reasons == []
    details = records[-1][1]["details"]
    assert records[-1][0][2] == "observed"
    assert details["candidate_title"] == "始まりの合図"
    assert details["source_title"] == "大胆不敵"
    assert details["candidate_slot"] == "candidate_center"
    assert details["source_slot"] == "visible_slot_r1c2"
    assert details["controller_click_sequence"] == [
        "enumerate_target_slots",
        "provisional_next",
        "enumerate_source_deck",
        "cancel_to_target",
        "reselect_target",
        "next",
        "replay_source_pages",
        "reselect_source",
    ]
    assert details["change_click_count"] == 0


def test_day1_change_pair_never_selects_a_card_without_single_step(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1SelectChangePair()
    stops = []

    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda *args: (_ for _ in ()).throw(AssertionError("不得截图或点击")))
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen, reason: stops.append((screen, reason)) or True)

    assert not action.run(object(), SimpleNamespace(custom_action_param="{}"))
    assert stops == [("select_change_target", "page_execution_mode_not_single_step")]


def test_day1_temporary_change_pair_does_not_advance_when_the_candidate_name_differs(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1SelectChangePair()
    stops = []

    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda context, screen: b"target")
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen: image)
    candidates = [{"target_name": "タフネス", "slot": "candidate_left", "slot_roi": [158, 837, 127, 128], "confidence": 0.99}]

    def enumerate_targets(context, image):
        action._remember_pair_target_snapshot(candidates)
        return candidates, b"selected"

    monkeypatch.setattr(action, "_enumerate_pair_targets", enumerate_targets)
    calls = []
    monkeypatch.setattr(action, "_advance_pair_to_source", lambda *args: calls.append("next") or b"source")
    monkeypatch.setattr(action, "_browse_full_pair_source_deck", lambda *args: calls.append("browse") or b"source-browse-end")
    monkeypatch.setattr(action, "_cancel_pair_source_deck", lambda *args: calls.append("cancel") or b"target-after-cancel")
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen, reason: stops.append((screen, reason)) or True)

    assert not action.run(
        object(),
        SimpleNamespace(
            custom_action_param='{"execution_mode":"single_step","temporary_target_name":"始まりの合図","temporary_source_name":"スリリング+"}'
        ),
    )
    assert stops == [("select_change_target", "temporary_target_name_not_found")]
    assert calls == ["next", "browse", "cancel"]


def test_day1_temporary_change_pair_stops_when_the_target_name_is_ambiguous(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1SelectChangePair()
    stops = []

    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda context, screen: b"target")
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen: image)
    candidates = [
        {"target_name": "始まりの合図", "slot": "candidate_left", "slot_roi": [158, 837, 127, 128], "confidence": 0.99},
        {"target_name": "始まりの合図", "slot": "candidate_center", "slot_roi": [297, 837, 127, 128], "confidence": 0.99},
    ]

    def enumerate_targets(context, image):
        action._remember_pair_target_snapshot(candidates)
        return candidates, b"enumerated"

    monkeypatch.setattr(action, "_enumerate_pair_targets", enumerate_targets)
    calls = []
    monkeypatch.setattr(action, "_advance_pair_to_source", lambda *args: calls.append("next") or b"source")
    monkeypatch.setattr(action, "_browse_full_pair_source_deck", lambda *args: calls.append("browse") or b"source-browse-end")
    monkeypatch.setattr(action, "_cancel_pair_source_deck", lambda *args: calls.append("cancel") or b"target-after-cancel")
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen, reason: stops.append((screen, reason)) or True)

    assert not action.run(
        object(),
        SimpleNamespace(
            custom_action_param='{"execution_mode":"single_step","temporary_target_name":"始まりの合図","temporary_source_name":"スリリング+"}'
        ),
    )
    assert stops == [("select_change_target", "temporary_target_name_ambiguous")]
    assert calls == ["next", "browse", "cancel"]


def test_day1_source_snapshot_browses_all_pages_then_replays_a_later_page_slot(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1SelectChangePair()
    records = []
    stops = []
    slots = (("visible_slot_r1c1", [80, 638, 120, 120]),)
    probes = iter((b"page0-selected", b"page1-selected", b"page0-replay", b"page1-replay", b"page1-confirmed"))
    details = {
        b"page0-selected": {"matched_name": "大胆不敵", "effect_texts": ("効果",), "name_confidence": 0.99, "effect_confidence": 0.99},
        b"page1-selected": {"matched_name": "スリリング+", "effect_texts": ("効果",), "name_confidence": 0.99, "effect_confidence": 0.99},
        b"page0-replay": {"matched_name": "大胆不敵", "effect_texts": ("効果",), "name_confidence": 0.99, "effect_confidence": 0.99},
        b"page1-replay": {"matched_name": "スリリング+", "effect_texts": ("効果",), "name_confidence": 0.99, "effect_confidence": 0.99},
        b"page1-confirmed": {"matched_name": "スリリング+", "effect_texts": ("効果",), "name_confidence": 0.99, "effect_confidence": 0.99},
    }

    module.reset_runtime_hif_session()
    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_visible_source_slots", lambda: slots)
    monkeypatch.setattr(action, "_detect_source_deck_occupied_slots", lambda context, image: {"visible_slot_r1c1"})
    monkeypatch.setattr(action, "_probe_source_slot", lambda context, image, slot_id, slot_roi: next(probes))
    monkeypatch.setattr(action, "_source_detail_snapshot", lambda context, image: details[image])
    monkeypatch.setattr(action, "_capture_evidence", lambda image, label: SimpleNamespace(fingerprint=str(image)))
    monkeypatch.setattr(action, "_scroll_source_deck_page", lambda context, image, page_index: b"page1" if page_index == 0 else None)
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen, reason: stops.append((screen, reason)) or True)

    assert action._browse_full_pair_source_deck(object(), b"page0") == b"page1-selected"
    source_slot = next(slot for slot in module.get_runtime_hif_session().select_change_source_snapshot if slot.name == "スリリング+")
    selected = action._replay_pair_source_page(object(), b"page0", source_slot)

    assert selected is not None
    source, _ = selected
    assert source["matched_name"] == "スリリング+"
    assert source_slot.slot_id == "visible_slot_r1c1"
    assert source_slot.page_index == 1
    assert [item.name for item in module.get_runtime_hif_session().select_change_source_snapshot] == ["大胆不敵", "スリリング+"]
    assert stops == []


def test_day1_source_snapshot_stops_on_duplicate_name_without_reselecting_or_change(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1SelectChangePair()
    stops = []
    slots = (
        ("visible_slot_r1c1", [80, 638, 120, 120]),
        ("visible_slot_r1c2", [227, 638, 120, 120]),
    )
    details = {
        b"first": {"matched_name": "スリリング+", "effect_texts": ("効果",), "name_confidence": 0.99, "effect_confidence": 0.99},
        b"second": {"matched_name": "スリリング+", "effect_texts": ("効果",), "name_confidence": 0.99, "effect_confidence": 0.99},
    }

    duplicate_slots = tuple(
        module.HIFSelectChangeSlot(slot_id=slot_id, slot_roi=tuple(slot_roi), name="スリリング+", confidence=0.99, frame_fingerprint=slot_id, page_index=0)
        for slot_id, slot_roi in slots
    )
    page = module.HIFSelectChangePage(
        page_index=0,
        signature=tuple((slot.slot_id, slot.name) for slot in duplicate_slots),
        slots=duplicate_slots,
    )
    candidates = [{"target_name": "始まりの合図", "slot": "candidate_left", "slot_roi": [158, 837, 127, 128], "confidence": 0.99}]

    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda context, screen: b"target")
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen: image)
    monkeypatch.setattr(action, "_enumerate_pair_targets", lambda context, image: (action._remember_pair_target_snapshot(candidates) or (candidates, b"target-enumerated")))
    monkeypatch.setattr(action, "_advance_pair_to_source", lambda *args: b"source")
    monkeypatch.setattr(
        action,
        "_browse_full_pair_source_deck",
        lambda context, image: module.get_runtime_hif_session().set_select_change_source_snapshot(duplicate_slots, (page,)) or b"source-browse-end",
    )
    monkeypatch.setattr(action, "_cancel_pair_source_deck", lambda context, image: b"target-after-cancel")
    monkeypatch.setattr(action, "_select_pair_target", lambda *args: (_ for _ in ()).throw(AssertionError("不得重选候选卡")))
    monkeypatch.setattr(action, "_replay_pair_source_page", lambda *args: (_ for _ in ()).throw(AssertionError("不得回放源牌页")))
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen, reason: stops.append((screen, reason)) or True)

    assert not action.run(
        object(),
        SimpleNamespace(custom_action_param='{"execution_mode":"single_step","temporary_target_name":"始まりの合図","temporary_source_name":"スリリング+"}'),
    )
    assert stops == [("select_change_source_deck", "temporary_source_name_ambiguous")]


def test_day1_temporary_change_pair_accepts_opaque_frame_only_after_exact_target_ocr(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1SelectChangePair()
    stops = []
    evidence = SimpleNamespace(fingerprint=None)

    monkeypatch.setattr(action, "_capture_evidence", lambda image, label: evidence)
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: True)
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda context, screen: object())
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: True)
    monkeypatch.setattr(action, "_read_pair_target_details", lambda context, image: {"target_name": "頂点へ"})
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen, reason: stops.append((screen, reason)) or True)

    selected = action._select_pair_target(
        object(),
        object(),
        "candidate_left",
        [158, 837, 127, 128],
        expected_target_name="頂点へ",
    )

    assert selected is not None
    assert selected[0]["slot"] == "candidate_left"
    assert stops == []


def test_day1_change_pair_exposes_the_target_detail_roi_required_by_the_reused_reader():
    module = _load_action_module()
    action = module.ProduceHIFDay1SelectChangePair()

    assert action._detail_name_roi() == action._target_detail_name_roi()


def test_day1_change_pair_uses_the_calibrated_change_button_roi(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1SelectChangePair()
    captured = {}

    def observed_button_roi(screen_id, button_id, fallback):
        captured.update(screen_id=screen_id, button_id=button_id, fallback=fallback)
        return fallback

    monkeypatch.setattr(action, "_observed_button_roi", observed_button_roi)
    monkeypatch.setattr(action, "_find_text_option", lambda context, image, expected, roi: object())

    assert action._result_anchor_confirmed(object(), b"confirmation")
    assert captured == {
        "screen_id": "select_change_source_deck",
        "button_id": "change",
        "fallback": [373, 1119, 255, 82],
    }


def test_day1_change_pair_accepts_a_readable_candidate_missing_from_the_catalog(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1SelectChangePair()

    monkeypatch.setattr(
        module.ProduceChooseHIFSelectChangeTargetAuto,
        "_read_target_details",
        lambda *args: {"name": "頂点へ", "target_name": None},
    )

    assert action._read_pair_target_details(object(), b"candidate")["target_name"] == "頂点へ"


def test_day1_temporary_change_commit_requires_the_expected_completion_text(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1TemporaryChangeCommit()
    action.ACTION_DELAY = 0
    records = []
    clicks = []

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda context, screen: b"source" if screen == "select_change_source_deck" else b"result")
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen: image)
    monkeypatch.setattr(action, "_source_detail_snapshot", lambda context, image: {"matched_name": "スリリング+", "name_confidence": 0.99})
    monkeypatch.setattr(action, "_find_text_option", lambda *args: SimpleNamespace(best_result=SimpleNamespace(box=[373, 1119, 255, 82])))
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append(list(box)) or True)
    monkeypatch.setattr(action, "_run_ocr", lambda *args: SimpleNamespace(hit=False))
    monkeypatch.setattr(action, "_read_change_completion_texts", lambda context, image: ("スリリング+を始まりの合図にチェンジしました",))
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)

    assert action.run(
        object(),
        SimpleNamespace(
            custom_action_param='{"execution_mode":"single_step","temporary_target_name":"始まりの合図","temporary_source_name":"スリリング+"}'
        ),
    )
    assert clicks == [[373, 1119, 255, 82]]
    assert records[-1][0][1:3] == ("confirm_temporary_select_change", "verified")


def test_day1_temporary_change_commit_stops_on_communication_error(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1TemporaryChangeCommit()
    action.ACTION_DELAY = 0
    records = []
    stops = []

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda context, screen: b"source" if screen == "select_change_source_deck" else b"error")
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen: image)
    monkeypatch.setattr(action, "_source_detail_snapshot", lambda context, image: {"matched_name": "スリリング+", "name_confidence": 0.99})
    monkeypatch.setattr(action, "_find_text_option", lambda *args: SimpleNamespace(best_result=SimpleNamespace(box=[373, 1119, 255, 82])))
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: True)
    monkeypatch.setattr(action, "_run_ocr", lambda *args: SimpleNamespace(hit=True))
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen, reason: stops.append((screen, reason)) or True)

    assert action.run(
        object(),
        SimpleNamespace(
            custom_action_param='{"execution_mode":"single_step","temporary_target_name":"始まりの合図","temporary_source_name":"スリリング+"}'
        ),
    )
    assert stops == [("select_change_result", "communication_error_after_change")]
    assert records[-1][0][1:3] == ("confirm_temporary_select_change", "unverified")


def test_day1_temporary_change_result_return_requires_scene3(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1TemporaryChangeResultReturn()
    action.ACTION_DELAY = 0
    stops = []
    screenshots = iter((b"result", b"unknown"))

    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_run_ocr", lambda *args: SimpleNamespace(hit=True))
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: True)
    monkeypatch.setattr(action, "_run_template", lambda *args, **kwargs: SimpleNamespace(hit=False))
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen, reason: stops.append((screen, reason)) or True)

    assert action.run(object(), SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert stops == [("select_change_result", "day1_scene3_not_restored_after_change")]


def test_day1_change_decision_stops_after_enumerating_unknown_candidates_without_advancing(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1SelectChangeByDecision()
    action.ACTION_DELAY = 0
    records = []
    stops = []
    images = iter((b"initial", b"left", b"center", b"right"))
    details = iter(
        (
            {"name": "頂点へ", "target_name": None, "ocr_texts": ("頂点へ",), "confidence": 0.99},
            {"name": "タフネス", "target_name": None, "ocr_texts": ("タフネス",), "confidence": 0.99},
            {"name": "プライド", "target_name": None, "ocr_texts": ("プライド",), "confidence": 0.99},
        )
    )
    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda context, screen: next(images))
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen: image)
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: screen == "select_change_target")
    monkeypatch.setattr(action, "_read_target_details", lambda context, image, names: dict(next(details)))
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append(list(box)) or True)
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen, reason: stops.append((screen, reason)) or True)

    assert not action.run(object(), SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert clicks == [[158, 837, 127, 128], [297, 837, 127, 128], [436, 837, 127, 128]]
    assert stops == [("select_change_target", "unknown_change_candidate")]
    assert records[-1][1]["details"]["unknown_factors"] == ("頂点へ", "タフネス", "プライド")


def test_day1_change_decision_reselects_only_the_unique_best_known_candidate(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1SelectChangeByDecision()
    action.ACTION_DELAY = 0
    records = []
    images = iter((b"initial", b"left", b"center", b"right", b"center-reselected"))
    details = iter(
        (
            {"name": "普通卡", "target_name": "普通卡", "ocr_texts": ("普通卡",), "confidence": 0.99},
            {"name": "好调卡", "target_name": "好调卡", "ocr_texts": ("好调卡",), "confidence": 0.99},
            {"name": "普通卡二", "target_name": "普通卡二", "ocr_texts": ("普通卡二",), "confidence": 0.99},
            {"name": "好调卡", "target_name": "好调卡", "ocr_texts": ("好调卡",), "confidence": 0.99},
        )
    )
    cards = {
        "普通卡": SimpleNamespace(tags=()),
        "好调卡": SimpleNamespace(tags=("good_condition",)),
        "普通卡二": SimpleNamespace(tags=()),
    }
    monkeypatch.setattr(module, "load_hif_catalog", lambda: SimpleNamespace(skill_names=tuple(cards), skill_cards=cards))
    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda context, screen: next(images))
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen: image)
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: screen == "select_change_target")
    monkeypatch.setattr(action, "_read_target_details", lambda context, image, names: dict(next(details)))
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append(list(box)) or True)

    assert action.run(object(), SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert clicks == [[158, 837, 127, 128], [297, 837, 127, 128], [436, 837, 127, 128], [297, 837, 127, 128]]
    ready = records[-1][1]["details"]
    assert ready["candidate_slot"] == "candidate_center"
    assert ready["next_click_count"] == 0
    assert ready["change_click_count"] == 0


def test_select_change_result_observer_records_verified_result_without_closing_dialog(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFSelectChangeResultObserve()
    records = []
    stop_reasons = []

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(module, "build_card_name_dict", lambda: {"大胆不敵": object(), "始まりの合図": object()})
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"change-result")
    monkeypatch.setattr(
        action,
        "_run_ocr",
        lambda *args, **kwargs: SimpleNamespace(
            hit=True,
            best_result=SimpleNamespace(text="大胆不敵を始まりの合図にチェンジしました", score=0.99, box=[60, 970, 580, 70]),
            all_results=[SimpleNamespace(text="大胆不敵を始まりの合図にチェンジしました", score=0.99, box=[60, 970, 580, 70])],
        ),
    )
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )

    assert action.run(object(), SimpleNamespace(custom_action_param="{}"))
    assert records[-1][0][1:3] == ("observe_select_change_result", "verified")
    assert stop_reasons == [("select_change_result", "select_change_result_observed_stop")]


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


def test_finals_ranking_transition_advances_only_to_confirmed_round1(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFFinalsRankingContinueAuto()
    action.ACTION_DELAY = 0
    records = []
    clicks = []

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"ranking" if not clicks else b"round1")
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: image == b"ranking" and screen_id == "finals_ranking_transition")
    monkeypatch.setattr(
        action,
        "_find_text_option",
        lambda context, image, phrases, roi: SimpleNamespace(
            best_result=SimpleNamespace(box=[245, 1140, 250, 80], text="タップして次へ")
        ),
    )
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append(list(box)) or True)
    monkeypatch.setattr(action, "_detect_confirmed_hif_transition", lambda context, image: "round1" if image == b"round1" else None)
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)

    assert action.run(
        object(),
        SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'),
    )
    assert clicks == [[245, 1140, 250, 80]]
    assert records[-1][0][1:3] == ("continue_finals_ranking", "verified")


def test_finals_ranking_transition_rejects_an_unconfirmed_source_page(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFFinalsRankingContinueAuto()
    stop_reasons = []

    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"unknown")
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: False)
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不得点击")))
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )

    assert action.run(
        object(),
        SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'),
    )
    assert stop_reasons == [("finals_ranking_transition", "finals_ranking_transition_page_not_confirmed")]


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


def test_day1_schedule_override_keeps_the_explicit_single_step_mode(monkeypatch):
    module = _load_action_module()
    action = module.ProduceChooseHIFEventAuto()
    reading = SimpleNamespace(
        page_observation=SimpleNamespace(is_unique=True, screen_id="finals_prepare", confidence=1.0),
        missing_fields=(),
        state=SimpleNamespace(day_remaining=6),
    )
    selected_modes = []
    events = [
        {"name": "Vo", "category": "Vo", "box": [0, 0, 1, 1]},
        {"name": "Da", "category": "Da", "box": [1, 0, 1, 1]},
        {"name": "Vi", "category": "Vi", "box": [2, 0, 1, 1]},
    ]

    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"schedule")
    monkeypatch.setattr(
        module.HIFStateReader,
        "from_context",
        lambda context, image: SimpleNamespace(read_finals_prepare_state=lambda: reading),
    )
    monkeypatch.setattr(action, "_get_available_events", lambda context, image: events)
    monkeypatch.setattr(action, "_record_journal", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        action,
        "_execute_event",
        lambda context, image, event: selected_modes.append((action._page_execution_mode, event)) or True,
    )

    assert action.run(object(), SimpleNamespace(custom_action_param='{"day1_lesson":"Vo","execution_mode":"single_step"}'))
    assert selected_modes == [(module.HIFExecutionMode.SINGLE_STEP, events[0])]


@pytest.mark.parametrize(
    "events",
    [
        [
            {"name": "Vo", "category": "Vo", "box": [0, 0, 1, 1]},
            {"name": "Da", "category": "Da", "box": [1, 0, 1, 1]},
        ],
        [
            {"name": "Vo", "category": "Vo", "box": [0, 0, 1, 1]},
            {"name": "Da", "category": "Da", "box": [1, 0, 1, 1]},
            {"name": "Vi", "category": "Vi", "box": [2, 0, 1, 1]},
            {"name": "Vi", "category": "Vi", "box": [3, 0, 1, 1]},
        ],
    ],
)
def test_day1_schedule_override_rejects_incomplete_candidates(monkeypatch, events):
    module = _load_action_module()
    action = module.ProduceChooseHIFEventAuto()
    reading = SimpleNamespace(
        page_observation=SimpleNamespace(is_unique=True, screen_id="finals_prepare", confidence=1.0),
        missing_fields=(),
        state=SimpleNamespace(day_remaining=6),
    )
    stops = []
    selected = []

    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"schedule")
    monkeypatch.setattr(
        module.HIFStateReader,
        "from_context",
        lambda context, image: SimpleNamespace(read_finals_prepare_state=lambda: reading),
    )
    monkeypatch.setattr(action, "_get_available_events", lambda context, image: events)
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, state, reason: stops.append((state, reason)) or True)
    monkeypatch.setattr(action, "_execute_event", lambda context, image, event: selected.append(event) or True)

    assert action.run(object(), SimpleNamespace(custom_action_param='{"day1_lesson":"Vo","execution_mode":"single_step"}'))
    assert stops == [("finals_action_select", "day1_lesson_candidates_incomplete")]
    assert selected == []


def test_schedule_selection_requires_a_new_task_before_confirmation(monkeypatch):
    module = _load_action_module()
    action = module.ProduceChooseHIFEventAuto()
    action.ACTION_DELAY = 0
    action._configure_page_execution(SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    records = []
    stop_reasons = []
    clicks = []
    screenshots = iter((b"selected",))

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
    assert clicks == [([100, 100, 40, 40], False)]
    assert stop_reasons == [("finals_action_select", "schedule_confirmation_requires_new_task")]
    assert records[-1][0][1:3] == ("select_schedule", "verified")


def test_schedule_transition_checks_class_options_as_the_expected_postcondition(monkeypatch):
    module = _load_action_module()
    action = module.ProduceChooseHIFEventAuto()

    monkeypatch.setattr(action, "_detect_screen_profile", lambda context, image: None)
    context = SimpleNamespace(
        run_recognition=lambda name, image: SimpleNamespace(hit=name == "ProduceHIFClassOptionFlag"),
    )

    assert action._detect_confirmed_hif_transition(context, b"class-options") == "class_options"


def test_wait_for_screen_profile_accepts_only_the_same_formal_pipeline_page(monkeypatch):
    module = _load_action_module()
    action = module.ProduceChooseHIFSelectChangeTargetAuto()

    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: False)
    monkeypatch.setattr(action, "_detect_confirmed_hif_transition", lambda context, image: "select_change_target")

    assert action._wait_for_screen_profile(object(), b"target", "select_change_target", attempts=0) == b"target"

    monkeypatch.setattr(action, "_detect_confirmed_hif_transition", lambda context, image: "class_options")
    assert action._wait_for_screen_profile(object(), b"target", "select_change_target", attempts=0) is None


def test_source_confirmation_rehydrates_an_explicitly_authorized_target_from_action_parameters(monkeypatch):
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
                '"selected_target_name":"成就","explicit_target_authorized":true,"explicit_source_authorized":true}'
            )
        ),
    )
    assert stop_reasons == []
    assert len(confirmations) == 1
    args, kwargs = confirmations[0]
    assert args[2:4] == ("大胆不敵", "成就")
    assert kwargs["explicit_source_authorized"] is True


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


def test_drink_overflow_commit_accepts_the_known_drink_reveal_transition(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDrinkOverflowObserve()
    monkeypatch.setattr(
        action,
        "_matches_screen_profile",
        lambda context, image, screen_id: screen_id == "drink_reward_reveal",
    )

    assert action._post_overflow_screen(object(), b"drink-reveal") == "drink_reward_reveal"


def test_preselected_drink_commit_requires_black_vinegar_effect_instead_of_ulong(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDrinkOverflowObserve()
    action.ACTION_DELAY = 0
    records = []
    expected_patterns = []

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))

    def fake_ocr(context, image, name, expected, roi):
        del context, image, name, roi
        expected_patterns.append(tuple(expected))
        if tuple(expected) == action._BLACK_VINEGAR_EFFECT:
            return SimpleNamespace(hit=True, best_result=SimpleNamespace(box=[180, 900, 260, 40]))
        return SimpleNamespace(hit=False, best_result=None)

    monkeypatch.setattr(action, "_run_ocr", fake_ocr)
    monkeypatch.setattr(
        action,
        "_find_text_option",
        lambda *args, **kwargs: SimpleNamespace(best_result=SimpleNamespace(box=[230, 1116, 260, 84])),
    )
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append(list(box)) or True)
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"finals")
    monkeypatch.setattr(action, "_post_overflow_screen", lambda context, image: "finals_prepare")
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)
    monkeypatch.setattr(action, "_stop_unsupported", lambda *args, **kwargs: True)

    assert action._commit_preselected_drinks(
        object(),
        b"overflow",
        SimpleNamespace(fingerprint="overflow"),
    )
    assert expected_patterns == [action._BLACK_VINEGAR_EFFECT]
    assert clicks == [[230, 1116, 260, 84]]
    assert records[-1][0][1:3] == ("resolve_drink_overflow", "verified")


def test_preselected_drink_commit_scrolls_once_before_rechecking_hidden_black_vinegar(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDrinkOverflowObserve()
    action.ACTION_DELAY = 0
    records = []
    black_vinegar_reads = iter((False, True))

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))

    def fake_ocr(context, image, name, expected, roi):
        del context, image, name, expected, roi
        hit = next(black_vinegar_reads)
        return SimpleNamespace(
            hit=hit,
            best_result=SimpleNamespace(box=[180, 850, 260, 40]) if hit else None,
        )

    monkeypatch.setattr(action, "_run_ocr", fake_ocr)
    swipes = []
    monkeypatch.setattr(
        action,
        "_swipe_with_verification",
        lambda *args, **kwargs: swipes.append((args[4], args[5], kwargs["duration"])) or True,
    )
    screenshots = iter((b"scrolled", b"finals"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(
        action,
        "_matches_screen_profile",
        lambda context, image, screen_id: image == b"scrolled" and screen_id == "drink_overflow",
    )
    monkeypatch.setattr(action, "_remaining_prompt", lambda context, image, expected: SimpleNamespace(hit=True))
    monkeypatch.setattr(
        action,
        "_find_text_option",
        lambda *args, **kwargs: SimpleNamespace(best_result=SimpleNamespace(box=[230, 1116, 260, 84])),
    )
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append(list(box)) or True)
    monkeypatch.setattr(action, "_post_overflow_screen", lambda context, image: "finals_prepare")
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)
    monkeypatch.setattr(action, "_stop_unsupported", lambda *args, **kwargs: True)

    assert action._commit_preselected_drinks(
        object(),
        b"overflow",
        SimpleNamespace(fingerprint="overflow"),
    )
    assert swipes == [((360, 1020), (360, 780), 300)]
    assert clicks == [[230, 1116, 260, 84]]


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
    action.START_TRANSITION_ATTEMPTS = 0
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


def test_start_produce_waits_for_a_known_target_after_loading(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFStartProduceAuto()
    action.ACTION_DELAY = 0
    action.CLICK_DELAY = 0
    records = []
    clicks = []
    screenshots = iter((b"before", b"loading", b"known"))

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: image == b"before")
    monkeypatch.setattr(action, "_detect_confirmed_hif_transition", lambda context, image: "schedule" if image == b"known" else None)
    monkeypatch.setattr(
        action,
        "_find_text_option",
        lambda context, image, phrases, roi: SimpleNamespace(hit=True, best_result=SimpleNamespace(box=[210, 1030, 300, 105])),
    )
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append((list(box), double)) or True)

    assert action.run(object(), SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert clicks == [([210, 1030, 300, 105], False)]
    assert records[-1][0][1:3] == ("start_produce", "verified")
    assert records[-1][1]["details"] == {"next_screen": "schedule", "transition_attempt": 1}


def test_card_single_step_keeps_blessing_plus_closed_without_active_status_model(monkeypatch):
    module = _load_action_module()

    action = module.ProduceCardsHIF()
    records = []
    approvals = []
    tasks = []
    target = module.CardDetection("cards", (100, 700, 120, 180), "祝福", "祝福+", playable=True)
    observation = SimpleNamespace(
        state=None,
        detections=[target],
        numerics={},
        missing_fields=(),
        screen_confidence=1.0,
    )
    reader = SimpleNamespace(read_exam_observation=lambda *args: observation)
    candidate = SimpleNamespace(
        target_id="hand-1",
        title="祝福",
        upgrade=SimpleNamespace(value="plus"),
        total_score=1,
        rejection_code=None,
        components=(),
    )
    decision = SimpleNamespace(
        status=module.RouteDecisionStatus.SELECTED,
        selected_target_id="hand-1",
        rejection_code=None,
        rejection_detail=None,
        candidates=(candidate,),
    )

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(module.ExamStateReader, "from_context", classmethod(lambda cls, context: reader))
    monkeypatch.setattr(module, "infer_card_playability", lambda *args: None)
    monkeypatch.setattr(module, "assemble_route_state", lambda *args, **kwargs: SimpleNamespace(state=object(), targets={"hand-1": target}))
    monkeypatch.setattr(module, "RinamiGarakutaRouteScorer", lambda: SimpleNamespace(decide=lambda state: decision))
    monkeypatch.setattr(action, "_read_card_display_score", lambda *args: 3731)
    monkeypatch.setattr(
        module,
        "load_hif_roi_calibration",
        lambda: SimpleNamespace(supports_exam_fields=lambda fields: True, device_id="test", updated_at="test"),
    )

    def approve(mode, **kwargs):
        approvals.append(kwargs)
        return SimpleNamespace(should_execute=False, reason="postcondition_not_supported")

    monkeypatch.setattr(module, "approve_card_execution", approve)
    monkeypatch.setattr(action, "_get_screenshot", lambda context: SimpleNamespace(size=(720, 1280)))
    monkeypatch.setattr(
        action,
        "_probe_round_details_metrics",
        lambda context, image, screen_state, **kwargs: ("116611", "3807%", image),
    )
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


def test_initial_round_safely_infers_zero_reprise_and_selects_entertainment():
    module = _load_action_module()
    from agent.hif.decisions.state import ActionKind, CardAction

    action = module.ProduceCardsHIF()
    observation = SimpleNamespace(
        state=SimpleNamespace(turn=9, reprise_count=99, focus=6),
        numerics={},
        missing_fields=("reprise",),
        detections=[
            module.CardDetection("cards", (48, 886, 164, 250), "静かな意志"),
            module.CardDetection("cards", (264, 884, 159, 250), "至高のエンタメ"),
            module.CardDetection("cards", (482, 884, 163, 250), "始まりの合図"),
        ],
    )

    assert action._infer_initial_reprise(observation, 9)
    assert observation.state.reprise_count == 0
    assert observation.numerics["reprise"].value == 0
    assert observation.missing_fields == ()

    resolved = action._resolve_initial_default_target(CardAction(ActionKind.PLAY_CARD, None, "default"), observation, 9)
    assert resolved.target_card == "至高のエンタメ"


@pytest.mark.parametrize(
    ("turn", "card_names", "expected_reason"),
    [
        (7, ("自然体の魅力", "お姉さんの感覚"), "reprise_recovery_turn_mismatch"),
        (8, ("お姉さんの感覚", "鳴り止まない拍手"), "reprise_recovery_hand_evidence_missing"),
        (
            8,
            ("自然体の魅力", "お姉さんの感覚", "至高のエンタメ"),
            "reprise_recovery_entertainment_still_in_hand",
        ),
    ],
)
def test_reprise_recovery_after_entertainment_rejects_incomplete_live_evidence(turn, card_names, expected_reason):
    module = _load_action_module()
    session = HIFRunSession()
    observation = SimpleNamespace(
        state=SimpleNamespace(turn=turn, reprise_count=99),
        numerics={},
        missing_fields=("reprise",),
        detections=[module.CardDetection("cards", (index * 160, 884, 150, 250), name) for index, name in enumerate(card_names)],
    )

    recovered, reason = module.ProduceCardsHIF._recover_reprise_after_entertainment(observation, session, "round1", 9)

    assert not recovered
    assert reason == expected_reason
    assert observation.state.reprise_count == 99
    assert observation.numerics == {}
    assert observation.missing_fields == ("reprise",)
    assert not session.card_was_played("round1", "至高のエンタメ")


@pytest.mark.parametrize(
    ("round_key", "total_turns", "missing_fields", "expected_reason"),
    [
        ("round2", 9, ("reprise",), "reprise_recovery_round_mismatch"),
        ("round1", 8, ("reprise",), "reprise_recovery_total_turns_mismatch"),
        ("round1", 9, (), "reprise_recovery_not_missing"),
        ("round1", 9, ("reprise", "focus"), "reprise_recovery_other_fields_missing"),
    ],
)
def test_reprise_recovery_after_entertainment_never_overwrites_read_or_incomplete_state(
    round_key, total_turns, missing_fields, expected_reason
):
    module = _load_action_module()
    session = HIFRunSession()
    observation = SimpleNamespace(
        state=SimpleNamespace(turn=8, reprise_count=1),
        numerics={"reprise": module.NumericRead("reprise", "1", 1)},
        missing_fields=missing_fields,
        detections=[
            module.CardDetection("cards", (214, 884, 159, 250), "自然体の魅力"),
            module.CardDetection("cards", (380, 884, 159, 250), "お姉さんの感覚"),
        ],
    )

    recovered, reason = module.ProduceCardsHIF._recover_reprise_after_entertainment(
        observation, session, round_key, total_turns
    )

    assert not recovered
    assert reason == expected_reason
    assert observation.state.reprise_count == 1
    assert observation.numerics["reprise"].value == 1
    assert observation.missing_fields == missing_fields
    assert session.played_cards == {}


def test_reprise_recovery_after_entertainment_records_the_verified_first_card():
    module = _load_action_module()
    session = HIFRunSession()
    observation = SimpleNamespace(
        state=SimpleNamespace(turn=8, reprise_count=99),
        numerics={},
        missing_fields=("reprise",),
        detections=[
            module.CardDetection("cards", (48, 886, 164, 250), "仕切り直し"),
            module.CardDetection("cards", (214, 884, 159, 250), "自然体の魅力"),
            module.CardDetection("cards", (380, 884, 159, 250), "お姉さんの感覚"),
            module.CardDetection("cards", (546, 884, 159, 250), "鳴り止まない拍手"),
        ],
    )

    recovered, reason = module.ProduceCardsHIF._recover_reprise_after_entertainment(observation, session, "round1", 9)

    assert recovered
    assert reason == "turn9_entertainment_played_without_shizen_in_pre_hand"
    assert observation.state.reprise_count == 0
    assert observation.numerics["reprise"].raw == "recovered_after_entertainment=0"
    assert observation.numerics["reprise"].value == 0
    assert observation.missing_fields == ()
    assert session.card_was_played("round1", "至高のエンタメ")


def test_initial_default_target_stays_unresolved_when_focus_is_insufficient():
    module = _load_action_module()
    from agent.hif.decisions.state import ActionKind, CardAction

    action = module.ProduceCardsHIF()
    observation = SimpleNamespace(
        state=SimpleNamespace(turn=9, focus=2),
        detections=[module.CardDetection("cards", (264, 884, 159, 250), "至高のエンタメ")],
    )
    original = CardAction(ActionKind.PLAY_CARD, None, "default")

    assert action._resolve_initial_default_target(original, observation, 9) is original


def test_initial_default_target_stays_unresolved_when_the_card_is_grey_and_unplayable():
    module = _load_action_module()
    from agent.hif.decisions.state import ActionKind, CardAction

    action = module.ProduceCardsHIF()
    observation = SimpleNamespace(
        state=SimpleNamespace(turn=9, focus=6),
        detections=[module.CardDetection("useless", (264, 884, 159, 250), "至高のエンタメ")],
    )
    original = CardAction(ActionKind.PLAY_CARD, None, "default")

    assert action._resolve_initial_default_target(original, observation, 9) is original


def test_play_card_target_resolution_excludes_grey_unplayable_cards():
    module = _load_action_module()
    from agent.hif.decisions.state import ActionKind, CardAction

    grey = module.CardDetection("useless", (48, 884, 190, 250), "自然体の魅力")
    playable = module.CardDetection("cards", (266, 884, 190, 250), "自然体の魅力")
    action = CardAction(ActionKind.PLAY_CARD, "自然体の魅力", "test")

    assert module.ProduceCardsHIF._find_play_card_targets(action, [grey]) == []
    assert module.ProduceCardsHIF._find_play_card_targets(action, [grey, playable]) == [playable]


def test_current_run_hand_detail_titles_only_fill_matching_empty_boxes():
    module = _load_action_module()
    session = HIFRunSession()
    known_box = (142, 884, 141, 248)
    session.record_hand_detail_name(known_box, "鳴り止まない拍手")
    missing = module.CardDetection("cards", known_box)
    already_named = module.CardDetection("cards", (19, 884, 138, 250), "話題沸騰")
    different = module.CardDetection("cards", (266, 884, 139, 250))

    module.ProduceCardsHIF._apply_current_run_hand_detail_names([missing, already_named, different], session)

    assert missing.card_name == "鳴り止まない拍手"
    assert missing.card_name_confidence == 1.0
    assert already_named.card_name == "話題沸騰"
    assert different.card_name == ""


def test_current_run_hand_detail_mapping_restores_confidence_only_after_all_fields_are_complete():
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    session = HIFRunSession()
    boxes = [(20 + index * 130, 884, 120, 250) for index in range(5)]
    names = ["話題沸騰", "鳴り止まない拍手", "夏夜に咲く思い出", "仕切り直し", "始まりの合図"]
    for box, name in zip(boxes, names, strict=True):
        session.record_hand_detail_name(box, name)
    observation = SimpleNamespace(
        detections=[module.CardDetection("cards", box) for box in boxes],
        missing_fields=("hand_names",),
        screen_confidence=0.88,
        state=SimpleNamespace(hand=None),
    )

    active = action._complete_current_run_hand_observation(observation, session)

    assert [detection.card_name for detection in active] == names
    assert observation.missing_fields == ()
    assert observation.screen_confidence == 1.0


@pytest.mark.parametrize(
    ("detail_count", "shifted_boxes", "conflicting_title", "missing_fields", "selected", "expected_reason"),
    [
        (4, False, False, (), False, "round1_detail_mapping_incomplete"),
        (5, True, False, (), False, "round1_detail_mapping_iou_conflict"),
        (5, False, True, (), False, "round1_detail_title_conflict"),
        (5, False, False, ("focus",), False, "round1_detail_state_incomplete"),
        (5, False, False, (), True, "round1_detail_requires_unselected_hand"),
    ],
)
def test_round1_detail_map_play_one_rejects_untrusted_input_before_any_click(
    detail_count, shifted_boxes, conflicting_title, missing_fields, selected, expected_reason
):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    boxes = [(20 + index * 170, 884, 170, 250) for index in range(5)]
    details = [{"box": list(box), "detail_title": "話題沸騰"} for box in boxes[:detail_count]]
    detection_boxes = [(500 + index * 20, 884, 170, 250) for index in range(5)] if shifted_boxes else boxes
    detections = [module.CardDetection("cards", box) for box in detection_boxes]
    if conflicting_title:
        detections[0].card_name = "別名"
        detections[0].card_name_confidence = 1.0
    observation = SimpleNamespace(
        detections=detections,
        missing_fields=missing_fields,
        state=SimpleNamespace(good_condition_turns=8),
    )

    target, reason = action._approve_round1_detail_mapped_topic_target(observation, details, selected_at_start=selected)

    assert target is None
    assert reason == expected_reason


def test_round1_detail_map_play_one_only_approves_one_non_grey_topic_card_with_good_condition():
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    boxes = [(20 + index * 170, 884, 170, 250) for index in range(5)]
    details = [{"box": list(box), "detail_title": "話題沸騰" if index == 2 else "別カード"} for index, box in enumerate(boxes)]
    detections = [module.CardDetection("cards", box) for box in boxes]
    observation = SimpleNamespace(detections=detections, missing_fields=(), state=SimpleNamespace(good_condition_turns=8))

    target, reason = action._approve_round1_detail_mapped_topic_target(observation, details, selected_at_start=False)

    assert target is detections[2]
    assert reason == "approved"

    detections[2].label = "useless"
    target, reason = action._approve_round1_detail_mapped_topic_target(observation, details, selected_at_start=False)
    assert target is None
    assert reason == "round1_detail_topic_target_not_unique"

    detections[2].label = "cards"
    for detection in detections:
        detection.card_name = ""
    details[0]["detail_title"] = "話題沸騰"
    target, reason = action._approve_round1_detail_mapped_topic_target(observation, details, selected_at_start=False)
    assert target is None
    assert reason == "round1_detail_topic_target_not_unique"


def test_card_single_step_rejects_a_route_decision_without_unique_target(monkeypatch):
    module = _load_action_module()

    action = module.ProduceCardsHIF()
    records = []
    stops = []
    observation = SimpleNamespace(
        state=None,
        detections=[],
        numerics={},
        missing_fields=(),
        screen_confidence=1.0,
    )
    reader = SimpleNamespace(read_exam_observation=lambda *args: observation)
    decision = SimpleNamespace(
        status=SimpleNamespace(),
        selected_target_id=None,
        rejection_code=SimpleNamespace(value="score_tie"),
        rejection_detail="并列",
        candidates=(),
    )

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(module.ExamStateReader, "from_context", classmethod(lambda cls, context: reader))
    monkeypatch.setattr(module, "infer_card_playability", lambda *args: None)
    monkeypatch.setattr(module, "assemble_route_state", lambda *args, **kwargs: SimpleNamespace(state=object(), targets={}))
    monkeypatch.setattr(module, "RinamiGarakutaRouteScorer", lambda: SimpleNamespace(decide=lambda state: decision))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: SimpleNamespace(size=(720, 1280)))
    monkeypatch.setattr(
        action,
        "_probe_round_details_metrics",
        lambda context, image, screen_state, **kwargs: ("116611", "3807%", image),
    )
    monkeypatch.setattr(action, "_get_health", lambda context, image: None)
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不得出牌")))
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen_state, reason: stops.append(reason) or True)
    context = SimpleNamespace(run_task=lambda task: None)

    assert action.run(
        context,
        SimpleNamespace(custom_action_param='{"preset_id":"rinami_good_condition_safe","round":"round1","execution_mode":"single_step"}'),
    )
    assert stops == ["route_decision_rejected:score_tie"]
    assert records[-1][1]["details"]["reason_code"] == "score_tie"


def test_card_observe_rejects_incomplete_route_state_without_legacy_defaults(monkeypatch):
    module = _load_action_module()
    from agent.hif.round_metrics import build_round_metrics

    action = module.ProduceCardsHIF()
    records = []
    observation = SimpleNamespace(
        state=None,
        detections=[],
        numerics={"deck_size": module.NumericRead("deck_size", "", None)},
        issues=(SimpleNamespace(field="deck_size", code=SimpleNamespace(value="missing"), detail=""),),
        missing_fields=("deck_size", "hand_playability"),
        screen_confidence=0.5,
        round_metrics=build_round_metrics({}),
    )
    reader = SimpleNamespace(read_exam_observation=lambda *args: observation)

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(module.ExamStateReader, "from_context", classmethod(lambda cls, context: reader))
    monkeypatch.setattr(module, "infer_card_playability", lambda *args: None)
    monkeypatch.setattr(action, "_get_screenshot", lambda context: SimpleNamespace(size=(720, 1280)))
    monkeypatch.setattr(action, "_get_health", lambda context, image: None)
    monkeypatch.setattr(action, "_finish_observation", lambda context, screen_state: True)
    context = SimpleNamespace(run_task=lambda task: None)

    assert action.run(
        context,
        SimpleNamespace(custom_action_param='{"round":"round1","execution_mode":"observe_and_stop"}'),
    )
    assert records[-1][0] == ("round1", "card_decision", "rejected")
    assert records[-1][1]["details"]["reason"] == "route_state_rejected"
    issues = records[-1][1]["details"]["route_state_issues"]
    assert any(issue["field"] == "deck_size" for issue in issues)


def test_card_postcondition_requires_target_to_leave_the_hand(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    target = module.CardDetection("cards", (264, 884, 159, 250), "至高のエンタメ")
    before = [target, module.CardDetection("cards", (48, 886, 164, 250), "静かな意志")]
    post = SimpleNamespace(
        detections=[module.CardDetection("cards", (48, 886, 164, 250), "静かな意志")],
        screen_confidence=1.0,
        missing_fields=(),
    )

    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda *args, **kwargs: b"stable-round")
    monkeypatch.setattr(action, "_get_health", lambda *args, **kwargs: {"current": 24})
    monkeypatch.setattr(
        module.ExamStateReader,
        "from_context",
        classmethod(lambda cls, context: SimpleNamespace(read_exam_observation=lambda *args: post)),
    )

    ok, details = action._read_card_postcondition(
        object(),
        b"after",
        "round1",
        module.ExamRound.HONSEN_R1,
        9,
        target,
        before,
    )

    assert ok
    assert details["before_hand"] == ["至高のエンタメ", "静かな意志"]
    assert details["after_hand"] == ["静かな意志"]


def test_card_postcondition_waits_for_the_draw_animation_to_restore_a_readable_hand(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    action.CLICK_DELAY = 0
    target = module.CardDetection("cards", (264, 884, 159, 250), "至高のエンタメ")
    observations = iter(
        (
            SimpleNamespace(detections=[], screen_confidence=0.5, missing_fields=("hand",)),
            SimpleNamespace(
                detections=[module.CardDetection("cards", (48, 886, 164, 250), "静かな意志")],
                screen_confidence=0.75,
                missing_fields=(),
            ),
        )
    )

    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda *args, **kwargs: b"round")
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda *args, **kwargs: b"round-stable")
    monkeypatch.setattr(action, "_matches_screen_profile", lambda *args, **kwargs: True)
    monkeypatch.setattr(action, "_get_health", lambda *args, **kwargs: {"current": 24})
    monkeypatch.setattr(
        module.ExamStateReader,
        "from_context",
        classmethod(lambda cls, context: SimpleNamespace(read_exam_observation=lambda *args: next(observations))),
    )

    ok, details = action._read_card_postcondition(
        object(),
        b"after",
        "round1",
        module.ExamRound.HONSEN_R1,
        9,
        target,
        [target],
    )

    assert ok
    assert details["post_hand_attempt"] == 2


def test_card_postcondition_waits_for_reprise_to_replace_a_temporarily_retained_target(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    action.POSTCONDITION_SETTLE_DELAY = 0
    target = module.CardDetection("cards", (264, 884, 159, 250), "自然体の魅力")
    observations = iter(
        (
            SimpleNamespace(detections=[target], screen_confidence=0.8, missing_fields=()),
            SimpleNamespace(
                detections=[module.CardDetection("cards", (48, 886, 164, 250), "始まりの合図")],
                screen_confidence=0.9,
                missing_fields=(),
            ),
        )
    )

    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda *args, **kwargs: b"round")
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda *args, **kwargs: b"round-stable")
    monkeypatch.setattr(action, "_matches_screen_profile", lambda *args, **kwargs: True)
    monkeypatch.setattr(action, "_get_health", lambda *args, **kwargs: {"current": 24})
    monkeypatch.setattr(
        module.ExamStateReader,
        "from_context",
        classmethod(lambda cls, context: SimpleNamespace(read_exam_observation=lambda *args: next(observations))),
    )

    ok, details = action._read_card_postcondition(
        object(), b"after", "round1", module.ExamRound.HONSEN_R1, 9, target, [target]
    )

    assert ok
    assert details["post_hand_attempt"] == 2
    assert details["after_hand"] == ["始まりの合図"]


def test_card_postcondition_rejects_a_target_that_never_leaves_the_hand(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    action.POSTCONDITION_ATTEMPTS = 2
    action.POSTCONDITION_SETTLE_DELAY = 0
    target = module.CardDetection("cards", (264, 884, 159, 250), "自然体の魅力")
    post = SimpleNamespace(detections=[target], screen_confidence=0.9, missing_fields=())

    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda *args, **kwargs: b"round")
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda *args, **kwargs: b"round-stable")
    monkeypatch.setattr(action, "_matches_screen_profile", lambda *args, **kwargs: True)
    monkeypatch.setattr(action, "_get_health", lambda *args, **kwargs: {"current": 24})
    monkeypatch.setattr(
        module.ExamStateReader,
        "from_context",
        classmethod(lambda cls, context: SimpleNamespace(read_exam_observation=lambda *args: post)),
    )

    ok, details = action._read_card_postcondition(
        object(), b"after", "round1", module.ExamRound.HONSEN_R1, 9, target, [target]
    )

    assert not ok
    assert details["reason"] == "target_card_still_in_hand"
    assert details["post_hand_attempt"] == 2


def test_card_postcondition_accepts_target_removal_as_a_semantic_state_change_for_zero_cost_card(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    action.POSTCONDITION_ATTEMPTS = 1
    target = module.CardDetection("cards", (264, 884, 159, 250), "話題沸騰")
    before_state = SimpleNamespace(
        turn=6,
        good_condition_turns=47,
        focus=5,
        stamina=33,
        reprise_count=2,
        deck_size=21,
    )
    post = SimpleNamespace(
        detections=[module.CardDetection("cards", (48, 886, 164, 250), "始まりの合図")],
        screen_confidence=1.0,
        missing_fields=(),
        state=SimpleNamespace(**vars(before_state)),
    )

    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda *args, **kwargs: b"stable-round")
    monkeypatch.setattr(action, "_get_health", lambda *args, **kwargs: {"current": 33})
    monkeypatch.setattr(
        module.ExamStateReader,
        "from_context",
        classmethod(lambda cls, context: SimpleNamespace(read_exam_observation=lambda *args: post)),
    )

    ok, details = action._read_card_postcondition(
        object(),
        b"after",
        "round1",
        module.ExamRound.HONSEN_R1,
        9,
        target,
        [target],
        before_state=before_state,
    )

    assert ok
    assert details["state_changed_fields"] == ["hand"]


def test_selected_card_confirmation_requires_exact_title_and_select_marker(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    expected_calls = []

    def fake_ocr(context, image, name, expected, roi):
        del context, image, name
        expected_calls.append((tuple(expected), tuple(roi)))
        return SimpleNamespace(hit=True)

    monkeypatch.setattr(action, "_run_ocr", fake_ocr)

    assert action._card_selection_confirmed(object(), b"selected", "至高のエンタメ")
    assert expected_calls == [
        ((r".*至高のエンタメ.*",), (180, 430, 360, 90)),
        ((r".*SELECT.*", r".*SELEC.*"), (0, 1080, 720, 100)),
    ]


def test_round_hand_detail_probe_clicks_each_unique_card_once_and_records_titles(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    action.ACTION_DELAY = 0
    records = []
    clicks = []
    tasks = []
    detections = [
        module.CardDetection("cards", (20, 884, 170, 250), "候选一", "候选一+", 0.91, 0.98),
        module.CardDetection("cards", (185, 884, 170, 250), "候选二", "候选二+", 0.92, 0.97),
        module.CardDetection("cards", (350, 884, 170, 250), "候选三", "候选三+", 0.93, 0.96),
        module.CardDetection("cards", (515, 884, 170, 250), "候选四", "候选四+", 0.94, 0.95),
        module.CardDetection("cards", (610, 884, 100, 250), "候选五", "候选五+", 0.95, 0.94),
    ]
    reader = SimpleNamespace(_read_detections=lambda: detections, _card_dict=["详情一", "详情二", "详情三", "详情四", "详情五"])
    titles = iter(
        [
            ("详情一", "详情一+", 0.99),
            ("详情二", "详情二+", 0.98),
            ("详情三", "详情三+", 0.97),
            ("详情四", "详情四+", 0.96),
            ("详情五", "详情五+", 0.95),
        ]
    )
    images = iter((b"selected-1", b"selected-2", b"selected-3", b"selected-4", b"selected-5"))

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    session = HIFRunSession()
    monkeypatch.setattr(module, "get_runtime_hif_session", lambda: session)
    monkeypatch.setattr(module.ExamStateReader, "from_context", classmethod(lambda cls, context: reader))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: screen_id == "round1")
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append(tuple(box)) or True)
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda context, screen_state: next(images))
    marker_calls = 0

    def marker_ocr(*args, **kwargs):
        nonlocal marker_calls
        marker_calls += 1
        return SimpleNamespace(hit=marker_calls > 1)

    monkeypatch.setattr(action, "_run_ocr", marker_ocr)
    monkeypatch.setattr(action, "_read_selected_card_title", lambda context, image, card_dict: next(titles))
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action._probe_round_hand_details(context, b"round", "round1")

    assert clicks == [detection.box for detection in detections]
    detail_records = [kwargs["details"] for args, kwargs in records if args[1:3] == ("probe_hand_card_detail", "verified")]
    assert [details["detail_title"] for details in detail_records] == ["详情一", "详情二", "详情三", "详情四", "详情五"]
    assert records[-1][0][1:3] == ("probe_hand_details", "verified")
    assert records[-1][1]["details"]["leaves_last_card_selected"] is True
    assert tasks == ["ProduceHIFRound1ReachedStop"]
    assert session.round_hand_probe_started is True


def test_round_hand_detail_probe_rejects_an_already_selected_hand_without_clicking(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    clicks = []
    stops = []

    monkeypatch.setattr(action, "_matches_screen_profile", lambda *args: True)
    monkeypatch.setattr(action, "_run_ocr", lambda *args, **kwargs: SimpleNamespace(hit=True))
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: clicks.append(args) or True)
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen_state, reason: stops.append(reason) or True)

    assert action._probe_round_hand_details(object(), b"selected", "round1")
    assert clicks == []
    assert stops == ["round_hand_probe_requires_unselected_hand"]


def test_round_hand_detail_probe_session_lock_prevents_retry_clicks(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    session = HIFRunSession(round_hand_probe_started=True)
    clicks = []
    stops = []

    monkeypatch.setattr(module, "get_runtime_hif_session", lambda: session)
    monkeypatch.setattr(action, "_matches_screen_profile", lambda *args: True)
    monkeypatch.setattr(action, "_run_ocr", lambda *args, **kwargs: SimpleNamespace(hit=False))
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: clicks.append(args) or True)
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen_state, reason: stops.append(reason) or True)

    assert action._probe_round_hand_details(object(), b"round", "round1")
    assert clicks == []
    assert stops == ["round_hand_probe_already_started"]


def test_round_hand_detail_probe_from_selected_skips_the_bound_card_and_clicks_each_other_card_once(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    action.ACTION_DELAY = 0
    records = []
    clicks = []
    tasks = []
    detections = [
        module.CardDetection("useless", (48, 884, 190, 250), "自然体の魅力", "自然体の魅力+", 0.95, 0.99),
        module.CardDetection("cards", (266, 884, 190, 250), "天賦の才", "天賦の才+", 0.94, 0.98),
        module.CardDetection("cards", (484, 884, 190, 250), "シュプレヒコール", "シュプレヒコール+", 0.93, 0.97),
    ]
    reader = SimpleNamespace(_read_detections=lambda: detections)
    titles = iter(
        [
            ("自然体の魅力", "自然体の魅力+", 0.99),
            ("天賦の才", "天賦の才+", 0.98),
            ("シュプレヒコール", "シュプレヒコール+", 0.97),
        ]
    )
    images = iter((b"selected-2", b"selected-3"))
    session = HIFRunSession()

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(module, "get_runtime_hif_session", lambda: session)
    monkeypatch.setattr(module.ExamStateReader, "from_context", classmethod(lambda cls, context: reader))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: screen_id == "round1")
    monkeypatch.setattr(action, "_run_ocr", lambda *args, **kwargs: SimpleNamespace(hit=True))
    monkeypatch.setattr(action, "_read_selected_card_title", lambda context, image, card_dict: next(titles))
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append(tuple(box)) or True)
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda context, screen_state: next(images))
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action._probe_round_hand_details(context, b"selected-1", "round1", allow_selected_start=True)

    assert clicks == [detections[1].box, detections[2].box]
    detail_records = [kwargs["details"] for args, kwargs in records if args[1:3] == ("probe_hand_card_detail", "verified")]
    assert [details["detail_title"] for details in detail_records] == ["自然体の魅力", "天賦の才", "シュプレヒコール"]
    assert detail_records[0]["already_selected"] is True
    assert tasks == ["ProduceHIFRound1ReachedStop"]


def test_selected_hand_detail_probe_records_double_upgrade_title_without_clicking(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    records = []
    clicks = []
    tasks = []
    target = module.CardDetection(
        "cards",
        (484, 884, 190, 250),
        "シュプレヒコール",
        "シュプレヒコール++",
        0.93,
        0.97,
    )
    reader = SimpleNamespace(_read_detections=lambda: [target])

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(module.ExamStateReader, "from_context", classmethod(lambda cls, context: reader))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda *args: True)
    monkeypatch.setattr(action, "_run_ocr", lambda *args, **kwargs: SimpleNamespace(hit=True))
    monkeypatch.setattr(
        action,
        "_read_selected_card_title",
        lambda context, image, card_dict: ("シュプレヒコール", "シュプレヒコール++", 0.99),
    )
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: clicks.append(args) or True)
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action._probe_selected_hand_detail(context, b"selected", "round1")
    assert clicks == []
    assert records[-1][0][1:3] == ("probe_selected_hand_detail", "verified")
    assert records[-1][1]["details"]["detail_title_raw"] == "シュプレヒコール++"
    assert records[-1][1]["details"]["controller_inputs"] == 0
    assert tasks == ["ProduceHIFRound1ReachedStop"]


def test_selected_marker_geometry_recovers_unique_card_when_caption_ocr_is_unavailable():
    module = _load_action_module()
    detections = [
        module.CardDetection("cards", (18, 884, 189, 250)),
        module.CardDetection("cards", (208, 884, 170, 250)),
    ]
    marker = SimpleNamespace(best_result=SimpleNamespace(box=(78, 1110, 88, 48)))

    assert module.ProduceCardsHIF._selected_marker_detection(marker, detections) is detections[0]


def test_turn_roi_probe_records_all_candidates_without_controller_input(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    records = []
    clicks = []
    tasks = []
    values = iter(("1", "7", "7", "", ""))

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda *args: True)

    def fake_ocr(*args, **kwargs):
        value = next(values)
        if not value:
            return SimpleNamespace(hit=False, best_result=None)
        return SimpleNamespace(hit=True, best_result=SimpleNamespace(text=value, score=0.99, box=[1, 2, 3, 4]))

    monkeypatch.setattr(action, "_run_ocr", fake_ocr)
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: clicks.append(args) or True)
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action._probe_turn_roi_candidates(context, b"round", "round1")
    assert clicks == []
    assert records[-1][0][1:3] == ("probe_turn_rois", "observed")
    assert [read["raw"] for read in records[-1][1]["details"]["reads"]] == ["1", "7", "7", "", ""]
    assert records[-1][1]["details"]["controller_inputs"] == 0
    assert tasks == ["ProduceHIFRound1ReachedStop"]


def test_counter_roi_probe_records_candidates_without_controller_input(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    records = []
    clicks = []
    tasks = []
    values = iter(
        (
            "40ターン",
            "40ターン",
            "40",
            "40ターン",
            "40ターン",
            "集中4",
            "集中4",
            "4",
            "7",
            "10",
            "0",
            "210",
            "116611",
            "3807%",
            "4回",
            "2回",
            "ターン内0回",
        )
    )

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda *args: True)

    def fake_ocr(*args, **kwargs):
        value = next(values)
        return SimpleNamespace(hit=True, best_result=SimpleNamespace(text=value, score=0.99, box=[1, 2, 3, 4]))

    monkeypatch.setattr(action, "_run_ocr", fake_ocr)
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: clicks.append(args) or True)
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action._probe_counter_roi_candidates(context, b"round", "round1")
    assert clicks == []
    assert records[-1][0][1:3] == ("probe_counter_rois", "observed")
    assert records[-1][1]["details"]["reads"]["good_condition_value_only"]["raw"] == "40"
    assert records[-1][1]["details"]["reads"]["focus_value_only"]["raw"] == "4"
    assert records[-1][1]["details"]["reads"]["right_skill_card_uses"]["raw"] == "4回"
    assert records[-1][1]["details"]["controller_inputs"] == 0
    assert tasks == ["ProduceHIFRound1ReachedStop"]


def test_status_detail_probe_opens_records_and_restores_the_same_round(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    action.CLICK_DELAY = 0
    records = []
    clicks = []
    tasks = []
    screenshots = iter((b"detail", b"returned"))
    ocr = SimpleNamespace(
        hit=True,
        best_result=SimpleNamespace(box=[230, 1115, 260, 85]),
        all_results=(
            SimpleNamespace(text="スキルカード使用数追加", score=0.99, box=[100, 200, 300, 40]),
            SimpleNamespace(text="あと1回", score=0.98, box=[100, 250, 200, 40]),
        )
    )

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda *args: True)
    monkeypatch.setattr(action, "_click_box_center", lambda context, roi, **kwargs: clicks.append(roi) or True)
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda *args: next(screenshots))
    monkeypatch.setattr(action, "_run_ocr", lambda *args, **kwargs: ocr)
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action._probe_status_detail(context, b"round", "round1", 7)
    assert clicks == [[15, 604, 55, 50], [230, 1115, 260, 85]]
    assert records[-2][0][1:3] == ("probe_status_detail", "observed")
    assert records[-2][1]["details"]["reads"][0]["text"] == "スキルカード使用数追加"
    assert records[-1][0][1:3] == ("close_status_detail", "verified")
    assert tasks == ["ProduceHIFRound1ReachedStop"]


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


def test_round_deck_probe_reads_count_and_returns_to_the_same_round(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    action.ACTION_DELAY = 0
    records = []
    images = iter((b"deck", b"round-returned"))
    clicks = []

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(
        action,
        "_matches_screen_profile",
        lambda context, image, screen_id: (image == b"round" and screen_id == "round1")
        or (image == b"deck" and screen_id == "skill_deck_view")
        or (image == b"round-returned" and screen_id == "round1"),
    )
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append(list(box)) or True)
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(images))
    monkeypatch.setattr(
        action,
        "_run_ocr",
        lambda *args, **kwargs: SimpleNamespace(hit=True, best_result=SimpleNamespace(text="スキルカード(22)")),
    )
    monkeypatch.setattr(
        action,
        "_find_text_option",
        lambda *args, **kwargs: SimpleNamespace(best_result=SimpleNamespace(box=[232, 1119, 256, 82])),
    )
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)

    count, returned_image = action._probe_round_deck_size(object(), b"round", "round1")

    assert (count, returned_image) == (22, b"round-returned")
    assert clicks == [
        [519, 1174, 80, 82],
        [232, 1119, 256, 82],
    ]
    assert records[-1][0][1:3] == ("probe_deck_size", "verified")


def test_round_deck_probe_recovers_read_only_hand_and_details_dialogs(monkeypatch):
    module = _load_action_module()
    action = module.ProduceCardsHIF()
    action.ACTION_DELAY = 0
    records = []
    images = iter((b"details", b"round", b"deck", b"round-returned"))
    clicks = []

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(
        action,
        "_matches_screen_profile",
        lambda context, image, screen_id: (image == b"hand-history" and screen_id == "hand_history_view")
        or (image == b"details" and screen_id == "round_details")
        or (image == b"round" and screen_id == "round1")
        or (image == b"deck" and screen_id == "skill_deck_view")
        or (image == b"round-returned" and screen_id == "round1"),
    )
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append(list(box)) or True)
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(images))
    monkeypatch.setattr(
        action,
        "_run_ocr",
        lambda *args, **kwargs: SimpleNamespace(hit=True, best_result=SimpleNamespace(text="スキルカード(22)")),
    )
    monkeypatch.setattr(
        action,
        "_find_text_option",
        lambda *args, **kwargs: SimpleNamespace(best_result=SimpleNamespace(box=[232, 1119, 256, 82])),
    )
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)

    count, returned_image = action._probe_round_deck_size(object(), b"hand-history", "round1")

    assert (count, returned_image) == (22, b"round-returned")
    assert clicks == [
        [232, 1119, 256, 82],
        [314, 1118, 92, 92],
        [519, 1174, 80, 82],
        [232, 1119, 256, 82],
    ]
    assert records[0][0][1:3] == ("observe_hand_history", "observed")
    assert records[-1][0][1:3] == ("probe_deck_size", "verified")


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


def test_day1_change_deck_round_trip_returns_to_scene3(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1ChangeDeckRoundTrip()
    action.ACTION_DELAY = 0
    records = []
    clicks = []
    screenshots = iter((b"scene3", b"deck", b"scene3-returned"))
    template_results = iter(
        (
            SimpleNamespace(hit=True, best_result=SimpleNamespace(box=[162, 330, 23, 46])),
            SimpleNamespace(hit=True, best_result=SimpleNamespace(box=[618, 1166, 82, 82])),
            SimpleNamespace(hit=True, best_result=SimpleNamespace(box=[162, 330, 23, 46])),
            SimpleNamespace(hit=True, best_result=SimpleNamespace(box=[618, 1166, 82, 82])),
        )
    )

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_run_template", lambda *args, **kwargs: next(template_results))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: image == b"deck" and screen_id == "skill_deck_view")
    monkeypatch.setattr(action, "_read_visible_cards", lambda context, image: image)
    monkeypatch.setattr(action, "_find_text_option", lambda *args, **kwargs: SimpleNamespace(best_result=SimpleNamespace(box=[232, 1119, 256, 82])))
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, **kwargs: clicks.append(list(box)) or True)
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)

    assert action.run(object(), SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert clicks == [[618, 1166, 82, 82], [232, 1119, 256, 82]]
    assert [record[0][1] for record in records] == ["open_skill_deck", "close_skill_deck"]


def test_day1_change_deck_uses_the_calibrated_sixteen_card_slots():
    module = _load_action_module()
    action = module.ProduceHIFDay1ChangeDeckRoundTrip()

    assert len(action.CARD_SLOTS) == 16
    assert action.CARD_SLOTS[0] == [48, 406, 142, 142]
    assert action.CARD_SLOTS[-1] == [528, 868, 142, 142]


def test_day1_change_deck_reads_an_hif_only_card_name_without_the_common_card_dictionary(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1ChangeDeckRoundTrip()
    action.ACTION_DELAY = 0
    records = []
    screenshots = iter((b"selected",))

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: image == b"selected" and screen_id == "skill_deck_view")
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: True)
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)
    monkeypatch.setattr(
        action,
        "_run_ocr",
        lambda *args, **kwargs: SimpleNamespace(
            hit=True,
            filtered_results=(SimpleNamespace(text="心・技・体", box=[210, 115, 180, 42], score=0.96),),
            all_results=(),
        ),
    )

    assert action._read_card_slots(object(), b"deck", ([48, 406, 142, 142],), 1) == b"selected"
    assert records[-1][1]["details"]["name"] == "心・技・体"


def test_day1_change_deck_reads_seventeen_slots_after_one_verified_scroll(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1ChangeDeckRoundTrip()
    slot_reads = []

    monkeypatch.setattr(action, "_read_deck_size", lambda context, image: 17)
    monkeypatch.setattr(action, "_read_card_slots", lambda context, image, boxes, start: slot_reads.append((tuple(boxes), start)) or image)
    monkeypatch.setattr(action, "_deck_grid_fingerprint", lambda image: {b"first": "a", b"scrolled": "b"}[image])
    monkeypatch.setattr(action, "_swipe_with_verification", lambda *args, **kwargs: True)
    monkeypatch.setattr(action, "_get_screenshot_or_stop", lambda context, screen_id: b"scrolled")
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: screen_id == "skill_deck_view")

    assert action._read_visible_cards(object(), b"first") == b"scrolled"
    assert [start for _, start in slot_reads] == [1, 17]
    assert len(slot_reads[0][0]) == 16
    assert slot_reads[1][0] == (action.CARD_SLOTS[12],)


def test_day1_change_deck_round_trip_stops_when_close_does_not_restore_scene3(monkeypatch):
    module = _load_action_module()
    action = module.ProduceHIFDay1ChangeDeckRoundTrip()
    action.ACTION_DELAY = 0
    records = []
    stop_reasons = []
    screenshots = iter((b"scene3", b"deck", b"unknown"))
    template_results = iter(
        (
            SimpleNamespace(hit=True, best_result=SimpleNamespace(box=[162, 330, 23, 46])),
            SimpleNamespace(hit=True, best_result=SimpleNamespace(box=[618, 1166, 82, 82])),
            SimpleNamespace(hit=False, best_result=None),
            SimpleNamespace(hit=False, best_result=None),
        )
    )

    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _journal(records))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_run_template", lambda *args, **kwargs: next(template_results))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: image == b"deck" and screen_id == "skill_deck_view")
    monkeypatch.setattr(action, "_read_visible_cards", lambda context, image: image)
    monkeypatch.setattr(action, "_find_text_option", lambda *args, **kwargs: SimpleNamespace(best_result=SimpleNamespace(box=[232, 1119, 256, 82])))
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: True)
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )

    assert action.run(object(), SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert stop_reasons == [("day1_change_deck", "scene3_not_restored_after_deck_close")]
