from agent.hif.adapters.hif_state_reader import HIFStateReader, parse_health, parse_p_points, parse_attributes, parse_remaining_day


class _MockStateOcr:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def read_ocr(self, name: str, roi: tuple[int, int, int, int]) -> str | None:
        del roi
        return self.values.get(name.removeprefix("HIFState_"))


def test_hif_state_parsers_only_return_trustworthy_values():
    assert parse_health("22/35") == (22, 35)
    assert parse_health("35/22") is None
    assert parse_remaining_day("H.I.F本戦まで 4日") == 4
    assert parse_remaining_day("7日") is None
    assert parse_p_points("1,280") == 1280
    assert parse_attributes("Vo 1116 Da 2633 Vi 1881") == {"Vo": 1116, "Da": 2633, "Vi": 1881}


def test_hif_state_reader_preserves_missing_values_instead_of_fabricating_defaults():
    reader = HIFStateReader(_MockStateOcr({"remaining_day": "4日", "health": "22/35", "p_points": "330"}))
    reading = reader.read_finals_prepare_state()

    assert reading.missing_fields == ()
    assert reading.state.day_remaining == 4
    assert reading.state.stamina == 22
    assert reading.state.max_stamina == 35
    assert reading.state.p_points == 330
    assert reading.state.screen_confidence == 1.0


def test_hif_state_reader_reports_missing_critical_fields():
    reading = HIFStateReader(_MockStateOcr({"remaining_day": "4日"})).read_finals_prepare_state()

    assert reading.state.stamina is None
    assert reading.state.p_points is None
    assert set(reading.missing_fields) == {"health", "p_points"}
    assert reading.state.screen_confidence == 0.33


def test_hif_state_reader_reuses_the_same_trusted_fields_for_interval():
    reading = HIFStateReader(_MockStateOcr({"health": "34/35", "p_points": "580"})).read_interval_state()

    assert reading.state.phase.value == "interval"
    assert reading.state.stamina == 34
    assert reading.state.p_points == 580
    assert reading.missing_fields == ()
