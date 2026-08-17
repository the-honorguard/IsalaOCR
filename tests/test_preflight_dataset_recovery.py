from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_latest_dataset_resolution_strips_bom_and_repairs_stale_pointer() -> None:
    common = read("automation/powershell/training-common.ps1")
    assert "function Get-LatestDatasetResolution" in common
    assert "TrimStart([char]0xFEFF)" in common
    assert "Sort-Object LastWriteTime -Descending" in common
    assert "function Repair-LatestDatasetPointer" in common
    assert "[Text.UTF8Encoding]::new($false)" in common
    assert "Repaired latest dataset pointer" in common


def test_recognition_dataset_check_accepts_core_dataset_without_audit_character_file() -> None:
    common = read("automation/powershell/training-common.ps1")
    preflight = read("automation/powershell/preflight.ps1")
    assert '$required = @(\"train.txt\", \"val.txt\", \"test.txt\", \"manifest.json\")' in common
    assert '$optional = @(\"characters.txt\")' in common
    dataset_check = preflight.split('"dataset-check" {', 1)[1].split('"baseline" {', 1)[0]
    assert "Add-IsalaDatasetCheckResult" in dataset_check
    assert "-RequireDictionary" not in dataset_check


def test_training_requires_dictionary_but_reports_remediation_instead_of_crashing() -> None:
    preflight = read("automation/powershell/preflight.ps1")
    assert "Dataset {0} is present, but dict.txt has not yet been synchronized" in preflight
    assert "Open Stap 18 · Recognition-dataset valideren" in preflight
    train_gpu = preflight.split('"train-gpu" {', 1)[1].split('"train-cpu" {', 1)[0]
    assert "Add-IsalaDatasetCheckResult" in train_gpu
    assert "-RequireDictionary" in train_gpu
