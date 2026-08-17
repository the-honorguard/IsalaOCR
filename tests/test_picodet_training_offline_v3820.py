from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_picodet_pretrain_is_supported_by_shared_downloader():
    runner = (ROOT / "automation/training_runtime/paddlex_runner.py").read_text(encoding="utf-8")
    assert '"PicoDet-S": "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_pretrained_model/PicoDet-S_pretrained.pdparams"' in runner


def test_localization_training_forces_local_pretrain_and_keeps_log():
    runner = (ROOT / "automation/training_runtime/localization_runner.py").read_text(encoding="utf-8")
    assert 'ISALA_PICODET_PRETRAIN' in runner
    assert 'Train.pretrain_weight_path={pretrain}' in runner
    assert 'paddlex_train.log' in runner
    assert 'stderr=subprocess.STDOUT' in runner


def test_training_launcher_materializes_missing_picodet_weight():
    script = (ROOT / "automation/powershell/train-localization-model.ps1").read_text(encoding="utf-8")
    assert 'PicoDet-S_pretrained.pdparams' in script
    assert 'download-pretrain --model PicoDet-S' in script
    assert 'PaddleX training error tail' in script


def test_step4_updates_component_state_without_full_page_refresh():
    source = (ROOT / "frontend/src/localization-workbench.ts").read_text(encoding="utf-8")
    assert "/api/v2/localization/workbench" in source
    assert "window.setTimeout(() => this.refresh(false), delay)" in source
    assert "document.hidden ? 30000" in source
    assert "window.location.reload" not in source
    assert "EventSource" not in source
