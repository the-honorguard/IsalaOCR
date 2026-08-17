from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_heavy_training_dependencies_are_separate_from_verification_layer() -> None:
    text = (ROOT / "infrastructure" / "docker" / "Dockerfile.training").read_text(encoding="utf-8")
    install_pos = text.index('python3 -m pip install --upgrade "${PADDLE_PACKAGE}"')
    install_run_end = text.index("\n\nRUN python3 - <<'PYVERIFY'", install_pos)
    verify_pos = text.index("RUN python3 - <<'PYVERIFY'")
    assert install_pos < install_run_end <= verify_pos
    install_block = text[install_pos:install_run_end]
    assert "PYVERIFY" not in install_block
    assert "importlib.metadata" not in install_block


def test_prepare_step_materializes_exact_cpu_and_gpu_image_tags() -> None:
    text = (ROOT / "automation" / "powershell" / "prepare-training.ps1").read_text(encoding="utf-8")
    assert "--profile training-build build training-image-cpu" in text
    assert "--profile training-build build training-image-gpu" in text
    assert "--profile training-build build training-image-gpu-detection" in text
    assert "function Assert-DockerImage" in text
    assert text.count("Assert-DockerImage -Image $image") >= 3


def test_training_image_revision_can_remain_cached_across_host_only_hotfix() -> None:
    app_version = (ROOT / "project" / "VERSION").read_text(encoding="utf-8").strip()
    image_version = (ROOT / "project" / "TRAINING_IMAGE_VERSION").read_text(encoding="utf-8").strip()
    compose = (ROOT / "infrastructure" / "docker" / "compose.yaml").read_text(encoding="utf-8")
    assert app_version == "3.14.0"
    assert image_version == "3.8.4"
    assert compose.count('image: "isalaocr-training-cpu:${ISALA_TRAINING_IMAGE_VERSION:-3.8.4}"') >= 5
    assert compose.count('image: "isalaocr-training-gpu:${ISALA_TRAINING_IMAGE_VERSION:-3.8.4}"') >= 2
    assert "localization-model-prep" in compose

def test_training_operations_use_prebuilt_images_without_building_or_pulling() -> None:
    for name in (
        "check-training-dataset.ps1",
        "train-recognition-model.ps1",
        "export-recognition-model.ps1",
    ):
        text = (ROOT / "automation" / "powershell" / name).read_text(encoding="utf-8")
        assert "Assert-TrainingImagePrepared" in text
        assert "--pull never" in text
        assert "--no-build" not in text
        assert "--build" not in text


def test_compose_run_does_not_use_unsupported_no_build_flag() -> None:
    for path in (ROOT / "automation" / "powershell").glob("*.ps1"):
        text = path.read_text(encoding="utf-8")
        assert "run --rm --no-build" not in text


def test_missing_prebuilt_image_has_direct_option_one_instruction() -> None:
    common = (ROOT / "automation" / "powershell" / "training-common.ps1").read_text(encoding="utf-8")
    assert "function Get-TrainingImageVersion" in common
    assert "function Test-TrainingImagePrepared" in common
    assert "function Assert-TrainingImagePrepared" in common
    assert "Stap 1 · Voorbereiding" in common
    assert 'return "isalaocr-training-${Device}:$version"' in common
