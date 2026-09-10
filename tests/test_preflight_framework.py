from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_start_cmd_is_single_entrypoint() -> None:
    start = read("START.cmd")
    startup = read("automation/powershell/startup.ps1")
    assert "automation\\powershell\\startup.ps1" in start
    assert 'Join-Path $PSScriptRoot "launcher.ps1"' in startup
    assert "%*" in start


def test_launcher_supports_menu_check_repair_and_direct_action() -> None:
    launcher = read("automation/powershell/launcher.ps1")
    for mode in ("menu", "check", "repair", "action"):
        assert f'"{mode}"' in launcher
    assert "Invoke-IsalaPreflight -AllActions" in launcher
    assert "Invoke-IsalaPermissionRepair" in launcher


def test_every_menu_action_gets_preflight_before_execution() -> None:
    menu = read("automation/powershell/training-menu.ps1")
    check_pos = menu.index("Invoke-IsalaPreflight -ActionId $ActionId")
    execute_pos = menu.index("& $scriptPath @arguments")
    assert check_pos < execute_pos
    assert "Check-only mode: the task was not executed" in menu
    assert "S. Systeemcontroles" in menu
    assert "M. Onderhoud / permissieherstel" in menu
    assert '"4"  = @{ Name = "Cel-GT beoordelen"' in menu


def test_preflight_catalog_covers_detection_and_value_pipeline_actions() -> None:
    preflight = read("automation/powershell/preflight.ps1")
    for action_id in (1,2,5,6,7,8,9,10,11,12,13,20,21,22,24,25,26,27,28):
        assert f'"{action_id}"' in preflight
    assert "Add-IsalaCommonChecks" in preflight
    assert "Add-IsalaActionChecks" in preflight
    assert "Invoke-IsalaContainerPermissionCheck" in preflight
    assert "Invoke-IsalaGpuRuntimeCheck" in preflight
    assert "Save-IsalaCheckReport" in preflight
    assert "localization-train-gpu" in preflight
    assert "paddlex_validation" in preflight

def test_permission_repair_is_scoped_and_verified() -> None:
    preflight = read("automation/powershell/preflight.ps1")
    assert "workspace-repair repair --json" in preflight
    assert 'Invoke-IsalaPreflight -ActionId "1"' in preflight
    assert "chown -R" not in preflight


def test_successful_doctor_json_wins_over_compose_cleanup_timeout() -> None:
    preflight = read("automation/powershell/preflight.ps1")
    pass_check = preflight.index('$reportedPass = (')
    timeout_failure = preflight.index('if ($null -ne $result -and $result.TimedOut)')
    assert pass_check < timeout_failure
    assert '\"failure_count\"\\s*:\\s*0' in preflight
    assert '\"passed\"\\s*:\\s*true' in preflight


def test_each_executable_pipeline_action_script_has_direct_preflight_guard() -> None:
    preflight = read("automation/powershell/preflight.ps1")
    expected_scripts = {
        "prepare-training.ps1", "collect-training-data.ps1",
        "build-localization-dataset.ps1", "validate-localization-dataset.ps1",
        "train-localization-model.ps1", "evaluate-localization.ps1",
        "compare-localization.ps1", "activate-localization-model.ps1",
        "redetect-localization.ps1", "detection-quality-report.ps1",
        "prepare-mapping-data.ps1", "apply-mappings.ps1", "read-mapped-values.ps1",
        "build-training-dataset.ps1", "check-training-dataset.ps1",
        "train-recognition-model.ps1", "evaluate-recognition-pipeline.ps1",
        "register-activate-recognition.ps1",
    }
    for script in expected_scripts:
        assert script in preflight
        source = read(f"automation/powershell/{script}")
        assert "Assert-IsalaActionPreflight" in source

