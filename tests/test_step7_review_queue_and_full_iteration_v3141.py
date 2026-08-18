from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_step7_review_writes_are_serialized_and_retried():
    source = read("application/src/isala_ocr/training/static/step7-single-panel.js")
    assert "reviewNetworkQueue" in source
    assert "reviewNetworkBusy" in source
    assert "AbortController" in source
    assert "retryableStatus" in source
    assert "Netwerk traag" in source
    assert "reviews opgeslagen" in source


def test_full_table_iteration_completes_gt_and_reruns_active_model():
    source = read("automation/powershell/run-table-cell-pipeline.ps1")
    gt_index = source.index("open GT-bronnen afronden")
    build_index = source.index("dataset bouwen")
    train_index = source.index("GPU-training")
    activate_index = source.index("model activeren")
    rerun_index = source.index("nieuw actief model uitvoeren")
    assert gt_index < build_index < train_index < activate_index < rerun_index
    assert "set_ground_truth_source_review_completed" in source
    assert "table_cell_models\\active.json" in source
    assert "collect-training-data.ps1" in source
    assert "-TableModelId $activeModelId" in source


def test_step5_exposes_two_action_iteration_and_bulk_gt_completion():
    source = read("application/src/isala_ocr/training/templates/table_quality.html")
    assert "Alles laten draaien" in source
    assert "Markeer alle GT's als correct" in source
    assert "DRAAIEN → BEOORDELEN → DRAAIEN" in source
    assert "GT afronden indien nodig → dataset → validatie → training → activatie → nieuwe modelrun" in source
    assert "/api/detection-review/${encodeURIComponent(source.source_id)}/complete" in source
