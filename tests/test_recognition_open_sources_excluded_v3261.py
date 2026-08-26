from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_recognition_pipeline_does_not_require_all_table_sources_closed() -> None:
    build = (ROOT / "automation/powershell/build-training-dataset.ps1").read_text(encoding="utf-8")
    check = (ROOT / "automation/powershell/check-training-dataset.ps1").read_text(encoding="utf-8")
    cli = (ROOT / "application/src/isala_ocr/cli.py").read_text(encoding="utf-8")

    assert "Assert-IsalaDetectionGateOpen" not in build
    assert '"-m", "isala_ocr.cli"' in build
    assert "Assert-IsalaDetectionGateOpen" not in check
    assert "accepted Recognition-GT samples" in cli
    assert 'check-training-dataset.ps1") -Dataset "latest"' in build


def test_recognition_training_is_scoped_to_step8_approved_samples() -> None:
    gt = (ROOT / "application/src/isala_ocr/training/recognition_ground_truth.py").read_text(encoding="utf-8")
    dataset = (ROOT / "application/src/isala_ocr/training/dataset.py").read_text(encoding="utf-8")

    assert "list_ground_truth_sources(root)" in gt
    assert "_completed_ground_truth_sources" not in gt
    assert "RECOGNITION_GT_METHOD" in dataset
    assert "AND status='accepted'" in dataset
    assert "exact_label IS NOT NULL" in dataset
    assert "completed_source_ids" not in dataset


def test_recognition_evaluation_and_model_lifecycle_are_not_detection_gated() -> None:
    cli = (ROOT / "application/src/isala_ocr/cli.py").read_text(encoding="utf-8")
    evaluate = cli[cli.index("def _evaluate("):cli.index("def _compare(")]
    register = cli[cli.index("def _register("):cli.index("def _activate(")]
    activate = cli[cli.index("def _activate("):]
    assert "_require_detection_gate" not in evaluate
    assert "_require_detection_gate" not in register
    assert "_require_detection_gate" not in activate


def test_recognition_training_disables_removed_visualdl_in_paddlex_runner() -> None:
    runner = (ROOT / "automation/training_runtime/paddlex_runner.py").read_text(encoding="utf-8")
    train = runner[runner.index("def train("):runner.index("def evaluate(")]
    assert '"Global.use_visualdl=False"' in train
