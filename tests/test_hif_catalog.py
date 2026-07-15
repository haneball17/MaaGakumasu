from agent.hif.catalog import load_hif_catalog
from agent.hif.adapters.card_dict import build_card_name_dict


def test_catalog_loads_full_hif_skill_and_drink_data():
    catalog = load_hif_catalog()

    assert len(catalog.skill_cards) == 122
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


def test_catalog_distinguishes_granted_good_condition_from_a_good_condition_requirement():
    catalog = load_hif_catalog()

    blessing = catalog.skill_cards["祝福"]
    talk_time = catalog.skill_cards["トークタイム"]

    assert "good_condition" in blessing.tags
    assert "good_condition_grant" in blessing.tags
    assert "good_condition_requirement" not in blessing.tags
    assert "good_condition" in talk_time.tags
    assert "good_condition_requirement" in talk_time.tags
    assert "good_condition_grant" not in talk_time.tags


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


def test_catalog_includes_the_observed_hif_high_tension_reward():
    catalog = load_hif_catalog()

    high_tension = catalog.skill_cards["ハイテンション"]
    assert high_tension.is_lesson_once
    assert high_tension.stamina_cost == 0
    assert high_tension.effect_text == "元気+11 元気増加無効2ターン 消費体力減少3ターン"
    assert "recovery" in high_tension.tags
    assert "ハイテンション" in build_card_name_dict()
