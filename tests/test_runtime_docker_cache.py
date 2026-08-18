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


def test_runtime_freshness_ignores_independent_webui_layer() -> None:
    script = (ROOT / "automation" / "powershell" / "runtime-preparation.ps1").read_text(encoding="utf-8")

    # The labeler/WebUI has its own Dockerfile and is rebuilt independently by
    # label-training-data.ps1. Its presentation/control files must therefore not
    # invalidate the heavyweight OCR/mapping runtime.
    for path in (
        r"application\src\isala_ocr\training\static",
        r"application\src\isala_ocr\training\templates",
        r"application\src\isala_ocr\training\webui.py",
        r"application\src\isala_ocr\training\webui_server.py",
        r"application\src\isala_ocr\training\labeler.py",
        r"application\src\isala_ocr\training\labeler_server.py",
        r"application\src\isala_ocr\training\comparison_review_queue_web.py",
        r"application\src\isala_ocr\training\job_cancellation.py",
    ):
        assert path in script

    assert "Test-IsalaComputeRuntimeInput -File $file" in script
    assert '"application\\schemas"' in script
    assert '"application\\config"' not in script.split("foreach ($relativeDirectory in @(", 1)[1].split("))", 1)[0]


def test_labeler_restart_rebuilds_webui_from_current_checkout() -> None:
    launcher = (ROOT / "automation" / "powershell" / "label-training-data.ps1").read_text(encoding="utf-8")
    compose = (ROOT / "infrastructure" / "docker" / "compose.yaml").read_text(encoding="utf-8")

    assert "up --build -d --force-recreate labeler" in launcher
    assert "dockerfile: infrastructure/docker/Dockerfile.labeler" in compose
