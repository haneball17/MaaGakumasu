from agent.hif.catalog import load_hif_catalog
from agent.hif.adapters.card_dict import build_card_name_dict


def test_catalog_loads_full_hif_skill_and_drink_data():
    catalog = load_hif_catalog()

    assert len(catalog.skill_cards) == 121
    assert len(catalog.drinks) == 28
    assert catalog.custom_p_item_names("sense")[:2] == ("もじゃ（黄）", "花もじゃ（黄）")
    assert catalog.custom_p_item_names("sense", stage=2, parent="もじゃ（黄）") == ("花もじゃ（黄）",)
    assert catalog.custom_p_item_names("sense", stage=2, parent="ロボ（黄）") == ("羽ロボ（黄）", "花ロボ（黄）")
    assert catalog.skill_source_updated_at
    assert catalog.drink_source_updated_at


def test_catalog_exposes_key_card_costs_and_effect_tags():
    catalog = load_hif_catalog()

    oneesan = catalog.skill_cards["お姉さんの感覚"]
    shizen = catalog.skill_cards["自然体の魅力"]

    assert oneesan.stamina_cost == 6
    assert "good_condition" in oneesan.tags
    assert "reprise" in oneesan.tags
    assert shizen.focus_cost == 5
    assert "score" in shizen.tags


def test_catalog_schedule_maps_remaining_day_to_fixed_honisen_day():
    catalog = load_hif_catalog()

    assert catalog.schedule_for_remaining_day(6).action == "授業"
    assert catalog.schedule_for_remaining_day(4).action == "おでかけ"
    assert catalog.schedule_for_remaining_day(4).fallback == "差し入れ"
    assert catalog.schedule_for_remaining_day(1).action == "相談"
    assert catalog.schedule_for_remaining_day(0) is None


def test_full_catalog_is_used_by_card_name_dictionary():
    names = build_card_name_dict()

    assert "シュプレヒコール" in names
    assert "至高のエンタメ" in names
    assert "国民的アイドル" in names
