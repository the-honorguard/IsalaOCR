from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_docker_image_detection_is_centralized_and_uses_timeout_wrapper() -> None:
    common = read("automation/powershell/training-common.ps1")
    prepare = read("automation/powershell/prepare-training.ps1")
    status = read("automation/powershell/preparation-status.ps1")

    assert "function Get-DockerImageState" in common
    assert 'Invoke-DockerWithTimeout -Arguments @("image", "inspect", "--format", "{{.Id}}", $Image)' in common
    assert "^sha256:[0-9a-fA-F]{32,}$" in common
    assert "function Get-DockerImageId" in common

    # The preparation orchestrator must not use a separate native Docker inspect
    # implementation, otherwise Windows PowerShell can disagree with status.ps1.
    assert "& docker image inspect" not in prepare
    assert "Get-DockerImageState -Image $Image" in prepare
    assert "-RetryCount 4" in prepare

    assert "function Get-PreparationImageState" in status
    assert "Get-DockerImageState -Image $Image" in status
    assert 'Invoke-DockerWithTimeout -Arguments @("image","inspect"' not in status


def test_post_build_image_assertions_retry_for_docker_desktop_visibility() -> None:
    prepare = read("automation/powershell/prepare-training.ps1")
    for device, service in (
        ("cpu", "training-image-cpu"),
        ("gpu", "training-image-gpu"),
        ("gpu-detection", "training-image-gpu-detection"),
    ):
        build = prepare.index(f"--profile training-build build {service}")
        tail = prepare[build : build + 900]
        assert f"Get-TrainingImageName -Device {device}" in prepare[max(0, build - 400) : build + 200]
        assert "Assert-DockerImage -Image $image -RetryCount 4" in tail
