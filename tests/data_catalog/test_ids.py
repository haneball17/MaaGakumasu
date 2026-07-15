from uuid import UUID

import pytest

from tools.data_catalog.ids import stable_entity_id, stable_entity_uuid


def test_uuid5_is_stable_and_namespaced_by_source_key():
    first = stable_entity_id("skill_card", "seesaa", "123")

    assert first == stable_entity_id("skill_card", "seesaa", "123")
    assert first != stable_entity_id("skill_card", "seesaa", "124")
    assert first != stable_entity_id("drink", "seesaa", "123")
    assert UUID(first.removeprefix("skill_card:")).version == 5


def test_display_name_is_not_an_id_input():
    source_id = stable_entity_id("skill_card", "seesaa", "wiki-id-1")
    renamed_source_id = stable_entity_id("skill_card", "seesaa", "wiki-id-1")

    assert source_id == renamed_source_id


@pytest.mark.parametrize("parts", [("", "source", "1"), ("drink", "", "1"), ("drink", "source", "")])
def test_stable_id_rejects_empty_identity_parts(parts):
    with pytest.raises(ValueError):
        stable_entity_uuid(*parts)
