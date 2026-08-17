from pathlib import Path


def test_training_common_creates_host_side_run_directory_with_probe():
    text = Path("automation/powershell/training-common.ps1").read_text(encoding="utf-8")
    assert "function Initialize-TrainingRunDirectory" in text
    assert "New-Item -ItemType Directory" in text
    assert ".isalaocr-host-write-probe" in text
    assert "Remove-Item -LiteralPath $directory -Recurse -Force" in text


def test_all_run_producers_prepare_host_output_before_docker():
    expected = {
        "automation/powershell/check-training-dataset.ps1": 'Initialize-TrainingRunDirectory -Name "check-$Dataset" -Reset',
        "automation/powershell/train-recognition-model.ps1": "Initialize-TrainingRunDirectory -Name $RunId",
        "automation/powershell/evaluate-recognition-model.ps1": "Initialize-TrainingRunDirectory -Name $OutputName",
        "automation/powershell/compare-models.ps1": "Initialize-TrainingRunDirectory -Name $OutputName",
    }
    for filename, snippet in expected.items():
        text = Path(filename).read_text(encoding="utf-8")
        assert snippet in text
        assert "Convert-ToContainerTrainingPath" in text


def test_charset_report_probes_output_directory_before_write():
    text = Path("automation/training_runtime/paddlex_runner.py").read_text(encoding="utf-8")
    start = text.index("def _charset_report")
    end = text.index("\ndef _build_paddlex_command", start)
    section = text[start:end]
    assert "output.mkdir(parents=True, exist_ok=True)" in section
    assert "_assert_directory_writable(output)" in section
    assert section.index("_assert_directory_writable(output)") < section.index("charset_report.json")
