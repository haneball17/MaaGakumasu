from pathlib import Path

import numpy as np

from agent.hif.image_io import save_hif_image


def test_hif_image_writer_saves_uint8_bgra_as_png_without_pillow(tmp_path):
    image = np.zeros((2, 3, 4), dtype=np.uint8)
    image[:, :, 0] = 1
    image[:, :, 1] = 2
    image[:, :, 2] = 3
    image[:, :, 3] = 255
    output = tmp_path / "capture.png"

    save_hif_image(image, output)

    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_hif_image_writer_rejects_non_image_value(tmp_path):
    output = tmp_path / "capture.png"

    try:
        save_hif_image(object(), output)
    except TypeError:
        pass
    else:
        raise AssertionError("非图像对象应被拒绝")
    assert not output.exists()
