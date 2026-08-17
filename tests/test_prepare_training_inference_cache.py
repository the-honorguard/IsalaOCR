from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_prepare_training_full_flow_separates_parallel_downloads_from_sequential_installs():
    text = (ROOT / "automation" / "powershell" / "prepare-training.ps1").read_text(encoding="utf-8")
    assert "function Invoke-AllDownloadsParallel" in text
    assert 'Start-Job -Name "inference-models"' in text
    assert 'Start-Job -Name "pretrained-weight"' in text
    assert 'Start-Job -Name "cpu-base-image"' in text
    assert 'Start-Job -Name "gpu-base-image"' in text
    all_branch = text.index('if ($Component -eq "all")')
    full_pos = text.index("Invoke-AllDownloadsParallel", all_branch)
    install_pos = text.index('foreach($name in @("inference","cpu-detection","gpu-recognition","gpu-detection","pretrained"))', full_pos)
    assert full_pos < install_pos
    assert '--profile setup run --rm --pull never --entrypoint python model-prep' in text
    assert "probe-pretrain" in text
    assert "download-pretrain" in text
    assert "isala_ocr_model_manifest.json" in text
    assert "PP-OCRv6_medium_rec_pretrained.pdparams" in text


def test_training_runner_does_not_import_paddleocr_during_prepare():
    text = (ROOT / "automation" / "training_runtime" / "paddlex_runner.py").read_text(encoding="utf-8")
    prepare_block = text[text.index("def prepare("):text.index("\ndef check(")]
    assert "from paddleocr" not in prepare_block
    assert '"inference_cache_prepared_separately": True' in prepare_block


def test_menu_describes_both_model_preparation_steps():
    text = (ROOT / "automation" / "powershell" / "preflight.ps1").read_text(encoding="utf-8")
    assert "Prepare ALL models and training images" in text
    assert "Install inference OCR / table models" in text
    assert "Install GPU PaddleDetection / PicoDet-S stack" in text


def test_model_prep_includes_training_baseline_recognition_model():
    cli = (ROOT / "application" / "src" / "isala_ocr" / "cli.py").read_text(encoding="utf-8")
    prep = (ROOT / "application" / "src" / "isala_ocr" / "model_prep.py").read_text(encoding="utf-8")
    status = (ROOT / "automation" / "powershell" / "preparation-status.ps1").read_text(encoding="utf-8")
    assert 'get("default")' in cli
    assert "additional_recognition_models" in prep
    assert "PaddleRecognitionEngine" in prep
    assert 'official_models\\PP-OCRv6_medium_rec' in status


def test_named_baseline_evaluation_ignores_active_custom_model():
    cli = (ROOT / "application" / "src" / "isala_ocr" / "cli.py").read_text(encoding="utf-8")
    evaluate_block = cli[cli.index("def _evaluate("):cli.index("\ndef _compare(")]
    assert 'ocr_settings.pop("active_recognition_model_dir", None)' in evaluate_block
    assert 'ocr_settings.pop("recognition_model_dir", None)' in evaluate_block


def test_baseline_evaluation_has_host_side_offline_model_preflight():
    script = (ROOT / "automation" / "powershell" / "evaluate-recognition-model.ps1").read_text(encoding="utf-8")
    assert "Offline baseline model is missing" in script
    assert "official_models" in script
    assert "Run training menu option 1" in script
