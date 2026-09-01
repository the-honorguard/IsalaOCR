from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_paddledetection_install_omits_deprecated_sklearn_shim() -> None:
    dockerfile = read("infrastructure/docker/Dockerfile.training")
    assert "ARG INSTALL_PADDLEDETECTION=1" in dockerfile
    assert 'if [ "${INSTALL_PADDLEDETECTION}" = "1" ]' in dockerfile
    assert "paddlex --install PaddleDetection" in dockerfile
    assert "--deps_to_replace PaddleDetection.sklearn=None" in dockerfile
    assert "SKLEARN_ALLOW_DEPRECATED_SKLEARN_PACKAGE_INSTALL" not in dockerfile


def test_gpu_recognition_and_detection_are_separate_images() -> None:
    compose = read("infrastructure/docker/compose.yaml")
    assert 'INSTALL_PADDLEDETECTION: "0"' in compose
    assert 'INSTALL_PADDLEDETECTION: "1"' in compose
    assert 'image: "isalaocr-training-gpu:${ISALA_TRAINING_IMAGE_VERSION:-3.8.5}"' in compose
    assert 'image: "isalaocr-training-gpu-detection:${ISALA_TRAINING_IMAGE_VERSION:-3.8.5}"' in compose
    assert "training-image-gpu-detection:" in compose
    assert "trainer-gpu-detection:" in compose


def test_localization_gpu_uses_detector_specific_service_but_recognition_does_not() -> None:
    localization = read("automation/powershell/train-localization-model.ps1")
    recognition = read("automation/powershell/train-recognition-model.ps1")
    assert '"trainer-gpu-detection"' in localization
    assert '"training-gpu-detection"' in localization
    assert '"gpu-detection"' in localization
    assert '"trainer-gpu"' in recognition
    assert '"trainer-gpu-detection"' not in recognition


def test_preparation_actions_are_independently_exposed() -> None:
    preflight = read("automation/powershell/preflight.ps1")
    menu = read("automation/powershell/training-menu.ps1")
    webui = read("application/src/isala_ocr/training/webui.py")
    prepare = read("automation/powershell/prepare-training.ps1")
    for action_id in ("14", "15", "16", "17", "18"):
        assert f'"{action_id}" = @{{' in preflight
        assert f'"{action_id}"' in webui
    assert "Get-IsalaActionCatalog" in menu
    for component in ("inference", "cpu-detection", "gpu-recognition", "gpu-detection", "pretrained"):
        assert component in prepare
