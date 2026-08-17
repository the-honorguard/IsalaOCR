from pathlib import Path


def test_collect_script_does_not_shadow_powershell_input_variable() -> None:
    script = Path(__file__).parents[1] / "automation" / "powershell" / "collect-training-data.ps1"
    text = script.read_text(encoding="utf-8")
    assert "[string]$InputPath" in text
    assert "[string]$Input =" not in text
    assert '"--input", $normalizedInput' in text
