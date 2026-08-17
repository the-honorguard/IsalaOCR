from pathlib import Path


def test_worker_uses_explicit_noninteractive_cmd_wrapper_for_reliable_exit_code():
    root = Path(__file__).resolve().parents[1]
    script = (root / "automation" / "powershell" / "webui-worker.ps1").read_text(encoding="utf-8")
    assert "Start-Process -FilePath $env:ComSpec" in script
    assert "$powerShellCommand=" in script
    assert "-NonInteractive" in script
    assert '-File "{0}" action "{1}"' in script
    assert "$cmdArguments='/d /s /c call" in script
    assert "exit /b %ISALA_EXIT%" in script
    assert "$args=@(" not in script
    assert "Remove-Item $wrapperFile" in script


def test_worker_recovers_jobs_left_running_by_an_interrupted_worker():
    root = Path(__file__).resolve().parents[1]
    script = (root / "automation" / "powershell" / "webui-worker.ps1").read_text(encoding="utf-8")
    assert "function Complete-InterruptedJobs" in script
    assert 'Set-JobProperty $data "exit_code" 125' in script
    assert 'Set-JobProperty $data "progress_label" "Afgebroken door workerherstart"' in script
    assert "De taak is veilig als mislukt gemarkeerd" in script


def test_worker_uses_exitcode_sidecar_and_fatal_output_fallback():
    root = Path(__file__).resolve().parents[1]
    script = (root / "automation" / "powershell" / "webui-worker.ps1").read_text(encoding="utf-8")
    assert "$exitCodeFile=" in script
    assert "echo %ISALA_EXIT%" in script
    assert "[int]::TryParse($rawExit" in script
    assert "IsalaOCR failed:" in script
    assert "Fatale launcherfout gevonden" in script
