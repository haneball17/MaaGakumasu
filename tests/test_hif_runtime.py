from types import SimpleNamespace

from agent.hif.runtime import HIF_FRAME_SIZE, HIFFrameTransform, get_image_size, validate_hif_frame, propose_hif_frame_transforms


def test_hif_frame_accepts_pillow_style_size():
    validation = validate_hif_frame(SimpleNamespace(size=HIF_FRAME_SIZE))

    assert validation.ok
    assert (validation.width, validation.height) == HIF_FRAME_SIZE


def test_hif_frame_accepts_ndarray_style_shape():
    image = SimpleNamespace(shape=(1280, 720, 3))

    assert get_image_size(image) == HIF_FRAME_SIZE


def test_hif_frame_rejects_landscape_orientation_without_guessing_rotation():
    validation = validate_hif_frame(SimpleNamespace(width=1280, height=720))

    assert not validation.ok
    assert "方向错误" in validation.reason


def test_hif_frame_rejects_unknown_image_type():
    validation = validate_hif_frame(object())

    assert not validation.ok
    assert "无法" in validation.reason


def test_hif_frame_transform_maps_standard_coordinates_to_explicit_source_crop():
    transform = HIFFrameTransform((720, 1354), (0, 74, 720, 1280))

    assert transform.valid
    assert transform.to_source_point(0, 0) == (0, 74)
    assert transform.to_source_point(719, 1279) == (719, 1353)
    assert transform.to_source_roi((10, 20, 30, 40)) == (10, 94, 30, 40)
    assert transform.to_source_point(720, 0) is None


def test_hif_frame_transform_proposal_never_guesses_which_edge_contains_window_bar():
    transforms = propose_hif_frame_transforms(SimpleNamespace(size=(720, 1354)))

    assert [transform.crop for transform in transforms] == [(0, 0, 720, 1280), (0, 74, 720, 1280)]
    assert len(propose_hif_frame_transforms(SimpleNamespace(size=(720, 1279)))) == 0
    assert [transform.crop for transform in propose_hif_frame_transforms(SimpleNamespace(size=(720, 1280)))] == [(0, 0, 720, 1280)]
