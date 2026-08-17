from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_bootstrap():
    path = ROOT / "automation" / "training_runtime" / "paddlex_bootstrap.py"
    spec = importlib.util.spec_from_file_location("isala_paddlex_bootstrap", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_finds_explicit_paddleocr_repository(tmp_path, monkeypatch):
    bootstrap = _load_bootstrap()
    root = tmp_path / "PaddleOCR"
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "train.py").write_text("# train\n", encoding="utf-8")
    (root / "ppocr").mkdir()

    monkeypatch.setenv("PADDLE_PDX_PADDLEOCR_PATH", str(root))
    found, candidates = bootstrap._find_paddleocr_root()

    assert found == root.resolve()
    assert root.resolve() in candidates


def test_rejects_directory_without_training_entrypoint(tmp_path, monkeypatch):
    bootstrap = _load_bootstrap()
    invalid = tmp_path / "PaddleOCR"
    (invalid / "ppocr").mkdir(parents=True)
    monkeypatch.setattr(bootstrap, "_candidate_paddleocr_roots", lambda: [invalid])

    with pytest.raises(RuntimeError, match="tools/train.py"):
        bootstrap._find_paddleocr_root()


def test_bootstrap_disables_eager_repo_initialization_before_import(tmp_path, monkeypatch):
    bootstrap = _load_bootstrap()
    source = tmp_path / "paddlex-source"
    (source / "paddlex").mkdir(parents=True)
    paddleocr = tmp_path / "PaddleOCR"
    (paddleocr / "tools").mkdir(parents=True)
    (paddleocr / "tools" / "train.py").write_text("# train\n", encoding="utf-8")
    (paddleocr / "ppocr").mkdir()

    calls = []

    def fake_import(name):
        calls.append(name)
        if name == "paddlex":
            return object()
        if name == "paddlex.repo_apis.PaddleOCR_api":
            # Stop after environment/order assertions without building a full fake package.
            assert bootstrap.os.environ["PADDLE_PDX_EAGER_INIT"] == "False"
            assert bootstrap.os.environ["PADDLE_PDX_PADDLEOCR_PATH"] == str(paddleocr)
            raise RuntimeError("test stop")
        raise AssertionError(name)

    monkeypatch.setattr(bootstrap.importlib, "import_module", fake_import)
    with pytest.raises(RuntimeError, match="test stop"):
        bootstrap._register_text_recognition(
            "PP-OCRv6_medium_rec", source.resolve(), paddleocr.resolve()
        )

    assert calls == ["paddlex", "paddlex.repo_apis.PaddleOCR_api"]
    assert bootstrap.sys.path[0] == str(source.resolve())


def test_compose_mounts_hotfixable_training_runtime_into_reusable_images():
    import yaml

    compose = yaml.safe_load((ROOT / "infrastructure" / "docker" / "compose.yaml").read_text(encoding="utf-8"))
    for service_name in ("training-setup", "trainer-cpu", "trainer-gpu"):
        volumes = [str(item) for item in compose["services"][service_name]["volumes"]]
        assert "../../automation/training_runtime:/opt/isala-training:ro" in volumes

class _InaccessibleCandidate:
    def is_dir(self):
        raise PermissionError(13, "Permission denied", "/root/PaddleOCR")


def test_inaccessible_repository_candidate_is_skipped_instead_of_crashing():
    bootstrap = _load_bootstrap()
    assert bootstrap._is_paddleocr_root(_InaccessibleCandidate()) is False


def test_training_image_exposes_vendor_paddleocr_repository_to_runtime_user():
    dockerfile = (ROOT / "infrastructure" / "docker" / "Dockerfile.training").read_text(encoding="utf-8")
    assert 'destination = Path(os.environ["ISALA_PADDLEOCR_ROOT"])' in dockerfile
    assert 'PADDLEOCR_SOURCE_COMMIT=' in dockerfile
    assert 'os.chown(root, uid, gid)' in dockerfile
    assert 'PADDLE_PDX_PADDLEOCR_PATH=/opt/isala-paddleocr' in dockerfile
    assert 'PaddleOCR runtime identity:' in dockerfile

