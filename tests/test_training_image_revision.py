from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_common_exports_training_image_revision_to_compose() -> None:
    common = (ROOT / "automation" / "powershell" / "training-common.ps1").read_text(encoding="utf-8")
    assert '$env:ISALA_TRAINING_IMAGE_VERSION = Get-TrainingImageVersion' in common
    assert '"TRAINING_IMAGE_VERSION"' in common


def test_preparation_always_materializes_and_verifies_exact_versioned_tags() -> None:
    script = (ROOT / "automation" / "powershell" / "prepare-training.ps1").read_text(encoding="utf-8")
    assert "function Assert-DockerImage" in script
    for device, service in (("cpu", "training-image-cpu"), ("gpu", "training-image-gpu"), ("gpu-detection", "training-image-gpu-detection")):
        build = script.index(f"--profile training-build build {service}")
        function_name = {"cpu": "Install-CpuDetection", "gpu": "Install-GpuRecognition", "gpu-detection": "Install-GpuDetection"}[device]
        function_start = script.rfind(f"function {function_name}", 0, build)
        next_function = script.find("\nfunction ", build)
        block = script[function_start:next_function if next_function != -1 else len(script)]
        assert f"Get-TrainingImageName -Device {device}" in block
        assert "Assert-DockerImage -Image $image" in block
    assert "Test-TrainingImagePrepared -Device cpu" not in script
    assert "Test-TrainingImagePrepared -Device gpu" not in script
    assert "Test-TrainingImagePrepared -Device gpu-detection" not in script

