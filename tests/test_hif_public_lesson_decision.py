from agent.hif.domain import HIFPublicLessonPreview
from agent.hif.session import HIFRunSession
from agent.hif.route_planner import HIFRoutePlanner


def _preview(candidate: str, *, verified: bool = True) -> HIFPublicLessonPreview:
    return HIFPublicLessonPreview(
        candidate,
        -8,
        30,
        {"vo": 20 if candidate == "Da" else 0, "da": 120 if candidate == "Da" else 0, "vi": 0},
        {"vo": 321, "da": 549, "vi": 430},
        {"star": 30, "vo": 26 if candidate == "Da" else 0, "da": 185 if candidate == "Da" else 0, "vi": 0},
        verified,
    )


def test_fixed_da_public_lesson_strategy_requires_complete_verified_snapshots():
    decision = HIFRoutePlanner().choose_public_lesson(tuple(_preview(candidate) for candidate in ("Vo", "Da", "Vi")), "fixed_da_test")

    assert decision.candidate_id == "Da"
    assert decision.confidence == 1.0
    assert HIFRoutePlanner().choose_public_lesson((_preview("Da"),), "fixed_da_test").stop_reason == "public_lesson_candidates_incomplete"
    assert HIFRoutePlanner().choose_public_lesson(tuple(_preview(candidate, verified=candidate != "Vi") for candidate in ("Vo", "Da", "Vi")), "fixed_da_test").stop_reason == "public_lesson_preview_unverified"
    assert HIFRoutePlanner().choose_public_lesson(tuple(_preview(candidate) for candidate in ("Vo", "Da", "Vi")), "unknown").stop_reason == "unsupported_public_lesson_strategy"


def test_pending_public_lesson_keeps_only_verified_decision_data():
    session = HIFRunSession()
    previews = tuple(_preview(candidate) for candidate in ("Vo", "Da", "Vi"))

    session.set_pending_public_lesson("Da", 5, previews)

    assert session.pending_public_lesson is not None
    assert session.pending_public_lesson.candidate_id == "Da"
    assert session.pending_public_lesson.previews == previews
    session.clear_pending_public_lesson()
    assert session.pending_public_lesson is None
