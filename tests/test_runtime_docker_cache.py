from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dependency_layer_is_before_application_source() -> None:
    dockerfile = (ROOT / "infrastructure" / "docker" / "Dockerfile.runtime").read_text(encoding="utf-8")

    requirements_copy = dockerfile.index("COPY application/requirements/runtime.txt")
    dependency_install = dockerfile.index("pip install --requirement /tmp/requirements-runtime.txt")
    source_copy = dockerfile.index("COPY application/src /app/src")
    local_install = dockerfile.index("pip install --no-deps --no-cache-dir .")

    assert requirements_copy < dependency_install < source_copy < local_install


def test_buildkit_pip_cache_is_enabled() -> None:
    dockerfile = (ROOT / "infrastructure" / "docker" / "Dockerfile.runtime").read_text(encoding="utf-8")

    assert dockerfile.startswith("# syntax=docker/dockerfile:1.7")
    assert "id=isalaocr-pip-cache" in dockerfile
    assert "target=/root/.cache/pip" in dockerfile
    assert "--no-cache-dir --upgrade pip" not in dockerfile


def test_runtime_requirements_cover_all_project_extras() -> None:
    requirements = (ROOT / "application" / "requirements" / "runtime.txt").read_text(encoding="utf-8")

    expected = {
        "paddleocr[doc-parser]==3.7.0",
        "paddlepaddle==3.2.0",
        "Flask>=3.1,<4",
        "waitress>=3,<4",
        "pylibjpeg>=2,<3",
        "pylibjpeg-libjpeg>=2,<3",
        "pylibjpeg-openjpeg>=2,<3",
    }
    assert expected.issubset(set(requirements.splitlines()))
