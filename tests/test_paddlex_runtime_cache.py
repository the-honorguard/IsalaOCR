from pathlib import Path

import pytest

from isala_ocr.ocr.paddlex_runtime import prepare_paddlex_runtime


def test_prepare_paddlex_runtime_creates_writable_runtime_dirs(tmp_path: Path, monkeypatch):
    (tmp_path / "official_models").mkdir()
    monkeypatch.delenv("PADDLE_PDX_CACHE_HOME", raising=False)
    root = prepare_paddlex_runtime({"model_root": str(tmp_path), "allow_downloads": False})
    assert root == tmp_path
    assert (tmp_path / "temp").is_dir()
    assert (tmp_path / "locks").is_dir()
    assert (tmp_path / "func_ret").is_dir()


def test_prepare_paddlex_runtime_fails_before_import_for_unwritable_layout(tmp_path: Path):
    (tmp_path / "official_models").mkdir()
    # A regular file where PaddleX requires a directory reliably simulates a
    # non-writable/invalid cache layout without depending on Unix chmod as root.
    (tmp_path / "temp").write_text("blocked", encoding="utf-8")
    with pytest.raises(RuntimeError, match="runtime cache is not writable"):
        prepare_paddlex_runtime({"model_root": str(tmp_path), "allow_downloads": False})
