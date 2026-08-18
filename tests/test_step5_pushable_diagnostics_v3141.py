from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_step5_waits_for_review_queue_before_dataset_snapshot() -> None:
    script = (ROOT / "automation" / "powershell" / "run-table-cell-pipeline.ps1").read_text(encoding="utf-8-sig")

    wait_pos = script.index("Wait-IsalaComparisonReviewQueue -TimeoutSeconds 60")
    build_pos = script.index('Write-Host "Alles laten draaien: dataset bouwen..."')
    assert wait_pos < build_pos
    assert "comparison_review_queue.json" in script
    assert '"pending", "processing"' in script
    assert 'status -eq "failed"' in script
    assert "dataset met nog niet opgeslagen beoordelingen" in script


def test_step5_writes_tracked_text_and_json_diagnostics() -> None:
    script = (ROOT / "automation" / "powershell" / "run-table-cell-pipeline.ps1").read_text(encoding="utf-8-sig")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8-sig")

    assert '"diagnostics\\step5"' in script
    assert '"latest.txt"' in script
    assert '"latest.json"' in script
    assert "Start-Transcript" in script
    assert "Write-Step5DiagnosticsSummary" in script
    assert "hard_example_replay" in script
    assert "hard_example_replay_runtime" in script
    assert "Open Stap 6" in script
    assert (ROOT / "diagnostics" / "step5" / "latest.txt").is_file()
    assert (ROOT / "diagnostics" / "step5" / "latest.json").is_file()
    assert "diagnostics/step5/" not in gitignore


def test_step5_diagnostics_readme_explains_git_handoff() -> None:
    readme = (ROOT / "diagnostics" / "step5" / "README.md").read_text(encoding="utf-8")

    assert "git add diagnostics/step5/latest.txt diagnostics/step5/latest.json" in readme
    assert "git push" in readme
    assert "ChatGPT" in readme
