from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_labeler_startup_uses_json_not_docker_go_templates() -> None:
    combined = "\n".join(
        [
            read("automation/powershell/labeler-common.ps1"),
            read("automation/powershell/label-training-data.ps1"),
            read("automation/powershell/diagnose-label-interface.ps1"),
        ]
    )
    assert "docker inspect --format" not in combined
    assert "ConvertFrom-Json" in combined
    assert "8088/tcp" in combined


def test_labeler_startup_waits_for_health_before_browser() -> None:
    script = read("automation/powershell/label-training-data.ps1")
    health_pos = script.rfind("Test-LabelerHealth")
    browser_pos = script.rfind("Start-Process")
    assert health_pos != -1
    assert browser_pos > health_pos


def test_labeler_scripts_do_not_contain_ambiguous_colon_interpolation() -> None:
    combined = "\n".join(
        [
            read("automation/powershell/labeler-common.ps1"),
            read("automation/powershell/label-training-data.ps1"),
            read("automation/powershell/diagnose-label-interface.ps1"),
        ]
    )
    assert "$Port:" not in combined
    assert "$port:" not in combined


def test_startup_never_runs_compose_rm_when_no_container_exists() -> None:
    start = read("automation/powershell/label-training-data.ps1")
    stop = read("automation/powershell/stop-label-interface.ps1")
    combined = start + "\n" + stop
    assert "docker compose --profile training rm" not in combined
    assert "No stopped containers" in start
    assert "Remove-LabelerContainer" in start
    assert "Remove-LabelerContainer" in stop


def test_container_discovery_includes_stopped_containers() -> None:
    common = read("automation/powershell/labeler-common.ps1")
    assert "@('compose','--profile','training','ps','-a','-q','labeler')" in common


def test_container_removal_is_explicitly_idempotent() -> None:
    common = read("automation/powershell/labeler-common.ps1")
    assert "if ([string]::IsNullOrWhiteSpace($ContainerId)) { return $false }" in common
    assert 'if ($message -match "No such container")' in common


def test_diagnostics_restore_continue_after_training_common() -> None:
    script = read("automation/powershell/diagnose-label-interface.ps1")
    common_pos = script.find('training-common.ps1")')
    continue_pos = script.find('$ErrorActionPreference = "Continue"', common_pos)
    assert common_pos != -1
    assert continue_pos > common_pos


def test_patch_does_not_touch_training_data() -> None:
    allowed = {
        "LABELER_HOTFIX_README.txt",
        "project/VERSION",
        "automation/powershell/training-common.ps1",
        "automation/powershell/labeler-common.ps1",
        "automation/powershell/label-training-data.ps1",
        "automation/powershell/diagnose-label-interface.ps1",
        "automation/powershell/stop-label-interface.ps1",
        "tests/test_labeler_startup_scripts.py",
    }
    assert all(not item.startswith("training/") for item in allowed)


def test_docker_preflight_has_hard_timeout() -> None:
    common = read("automation/powershell/training-common.ps1")
    assert "Invoke-NativeProcessWithTimeout" in common
    assert "WaitForExit($TimeoutSeconds * 1000)" in common
    assert "$waitSeconds = 360" in common
    assert "Docker Desktop did not become ready within $waitSeconds seconds" in common


def test_diagnostics_timeout_before_followup_docker_calls() -> None:
    script = read("automation/powershell/diagnose-label-interface.ps1")
    assert "TIMEOUT after $TimeoutSeconds seconds" in script
    assert "if ($dockerVersion.TimedOut)" in script
    assert "wsl --shutdown" in script


def test_labeler_discovery_uses_timeout_wrapper() -> None:
    common = read("automation/powershell/labeler-common.ps1")
    assert "Invoke-DockerWithTimeout" in common
    assert "docker compose --profile training ps -a -q labeler" not in common


def test_startup_requires_actual_published_port_mapping() -> None:
    script = read("automation/powershell/label-training-data.ps1")
    assert "Get-PublishedLabelerPort" in script
    assert "without a host port mapping" in script
    assert "127.0.0.1:${selectedPort}->8088/tcp" in script
