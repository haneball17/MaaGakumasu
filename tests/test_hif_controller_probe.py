import importlib.util
from pathlib import Path


def _load_module():
    path = Path("tools/hif_controller_probe.py")
    spec = importlib.util.spec_from_file_location("hif_controller_probe", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_controller_probe_requires_existing_explicit_adb_path(tmp_path):
    module = _load_module()

    missing = tmp_path / "missing-adb.exe"
    existing = tmp_path / "adb.exe"
    existing.write_bytes(b"")

    assert module.resolve_adb_path(missing) is None
    assert module.resolve_adb_path(existing) == existing


def test_controller_probe_saves_image_object_with_save_method(tmp_path):
    module = _load_module()

    class _Image:
        def save(self, path):
            Path(path).write_bytes(b"png")

    target = tmp_path / "capture.png"
    module.save_screenshot(_Image(), target)

    assert target.read_bytes() == b"png"
