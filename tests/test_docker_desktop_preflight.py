from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_successful_docker_output_is_accepted_when_exit_code_is_unavailable() -> None:
    script = read("automation/powershell/training-common.ps1")
    assert "function Test-DockerEngineResult" in script
    assert "^Server:" in script
    assert "^\\s*Engine:" in script
    assert "^\\s*OS/Arch:\\s*linux/" in script


def test_process_exit_code_is_refreshed_for_windows_powershell_51() -> None:
    script = read("automation/powershell/training-common.ps1")
    assert "$process.WaitForExit()" in script
    assert "$process.Refresh()" in script
    assert "$exitCode = $null" in script


def test_docker_desktop_is_started_automatically_when_engine_is_unavailable() -> None:
    script = read("automation/powershell/training-common.ps1")
    assert "function Get-DockerDesktopExecutable" in script
    assert "Docker Desktop.exe" in script
    assert "function Start-DockerDesktopIfNeeded" in script
    assert "Start-Process -FilePath $executable" in script
    assert "Docker Engine is not available. Starting Docker Desktop" in script


def test_docker_startup_has_bounded_wait_and_continues_automatically() -> None:
    script = read("automation/powershell/training-common.ps1")
    assert "$waitSeconds = 360" in script
    assert "Waiting for Docker Desktop" in script
    assert "Docker Desktop is ready. Continuing" in script
    assert "did not become ready within $waitSeconds seconds" in script
