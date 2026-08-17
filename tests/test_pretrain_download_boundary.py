from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_pretrain_download_uses_network_enabled_model_prep_service() -> None:
    compose = read("infrastructure/docker/compose.yaml")
    script = read("automation/powershell/prepare-training.ps1")
    model_prep = compose[compose.index("  model-prep:"):compose.index("  model-prep-offline:")]
    training_setup = compose[compose.index("  training-setup:"):compose.index("  trainer-cpu:")]
    assert "automation/training_runtime:/opt/isala-training:ro" in model_prep
    assert "network_mode: none" not in model_prep
    assert "network_mode: none" in training_setup
    assert 'command: ["prepare", "--offline"' in training_setup
    assert "--entrypoint python model-prep" in script
    assert "probe-pretrain" in script
    assert "download-pretrain" in script


def test_runner_has_separate_probe_download_and_offline_validation_modes() -> None:
    runner = read("automation/training_runtime/paddlex_runner.py")
    assert "def probe_pretrain(" in runner
    assert "def download_pretrain(" in runner
    assert 'sub.add_parser("probe-pretrain")' in runner
    assert 'sub.add_parser("download-pretrain")' in runner
    assert 'prep.add_argument("--offline", action="store_true")' in runner
    prepare = runner[runner.index("def prepare("):runner.index("\ndef check(")]
    assert "if args.offline:" in prepare
    assert "Run the dedicated" in prepare
    assert "network-enabled pretrain download step first" in prepare


def test_preflight_checks_weight_size_and_conditional_connectivity() -> None:
    preflight = read("automation/powershell/preflight.ps1")
    assert "function Test-IsalaTrainingWeightReady" in preflight
    assert "Length -gt 1MB" in preflight
    assert "function Test-IsalaPretrainHostConnectivity" in preflight
    assert "Docker connectivity is verified again with the model-prep container before download" in preflight
