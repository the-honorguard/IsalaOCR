from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_step1_full_path_is_state_driven_and_skips_ready_components() -> None:
    script = (ROOT / "automation" / "powershell" / "prepare-training.ps1").read_text(encoding="utf-8")

    assert 'prepare-training-core.ps1' in script
    assert 'if ([bool]$snapshot.all_ready)' in script
    assert 'Nothing to download, build or revalidate.' in script
    assert 'if ([bool]$state.install.ready)' in script
    assert 'if (-not [bool]$state.download.ready)' in script
    assert '$installState -eq "unknown"' in script
    assert 'validating it without rebuilding' in script
    assert 'RequestedPhase "install"' in script
    assert 'RequestedPhase "check"' in script


def test_granular_preparation_actions_still_delegate_to_existing_core() -> None:
    script = (ROOT / "automation" / "powershell" / "prepare-training.ps1").read_text(encoding="utf-8")
    core = ROOT / "automation" / "powershell" / "prepare-training-core.ps1"

    assert core.is_file()
    assert 'if ($Component -ne "all" -or $Phase -ne "full")' in script
    assert 'Invoke-PreparationCore -Name $Component -RequestedPhase $Phase' in script


def test_runtime_build_does_not_recursively_chown_large_trees() -> None:
    dockerfile = (ROOT / "infrastructure" / "docker" / "Dockerfile.runtime").read_text(encoding="utf-8")

    assert 'chown -R "${APP_UID}:${APP_GID}" /output /models /training /tmp' not in dockerfile
    assert 'RUN install -d -o "${APP_UID}" -g "${APP_GID}"' in dockerfile
    assert 'chmod 1777 /tmp' in dockerfile


def test_training_image_version_is_not_bumped_for_orchestrator_only_fix() -> None:
    version = (ROOT / "project" / "TRAINING_IMAGE_VERSION").read_text(encoding="utf-8").strip()
    assert version == "3.8.5"
