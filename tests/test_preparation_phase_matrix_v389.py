from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_preparation_page_exposes_separate_download_install_and_check_phases() -> None:
    template = read("application/src/isala_ocr/training/templates/process_step.html")
    for label in (
        "Files / bron",
        "Downloadcheck",
        "Install / build",
        "Installatiecheck",
        "Volledig proces",
        "Onderhoud / opnieuw installeren",
    ):
        assert label in template
    assert "Download → install → check" in template
    assert "TABLE PIPELINE" in template
    assert "Stap 2 · Tabelregio’s selecteren" in template
    assert "PP-StructureV3" in template


def test_preparation_orchestrator_supports_component_phases_and_parallel_downloads() -> None:
    script = read("automation/powershell/prepare-training-core.ps1")
    assert '[ValidateSet("full","download","install","check")]' in script
    assert "function Invoke-AllDownloadsParallel" in script
    assert "Start-Job" in script
    assert "Receive-Job" in script
    # Heavy image builds deliberately remain sequential in the safe bulk path.
    assert "Install-Inference" in script
    assert "Install-CpuDetection" in script
    assert "Install-GpuRecognition" in script
    assert "Install-GpuDetection" in script
    assert "Install-Pretrained" in script


def test_preparation_status_tracks_phase_readiness_and_validation_markers() -> None:
    script = read("automation/powershell/preparation-status.ps1")
    assert 'schema_version="2.1"' in script
    assert "preparation_checks" in script
    assert "download=(PhaseState" in script
    assert "install=(InstalledPhase" in script
    assert 'Read-Marker "gpu_detection"' in script
    assert "image_id" in script
    assert "manifest_last_write_utc" in script
    assert "localization_manifest_last_write_utc" in script
    assert "weightBytes" in script


def test_phase_actions_are_internal_and_available_to_worker() -> None:
    preflight = read("automation/powershell/preflight.ps1")
    webui = read("application/src/isala_ocr/training/webui.py")
    for action_id in range(30, 48):
        assert f'"{action_id}" = @{{' in preflight
        assert f'"{action_id}":' in webui


def test_offline_checks_and_pkg_resources_compatibility_are_declared() -> None:
    compose = read("infrastructure/docker/compose.yaml")
    dockerfile = read("infrastructure/docker/Dockerfile.training")
    assert "model-prep-offline:" in compose
    assert "localization-model-check:" in compose
    assert compose.count("network_mode: none") >= 2
    assert '"setuptools<81"' in dockerfile
