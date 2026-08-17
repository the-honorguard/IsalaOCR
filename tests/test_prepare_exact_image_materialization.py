from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_training_setup_is_guarded_by_exact_cpu_image_inspection() -> None:
    script = (ROOT / "automation" / "powershell" / "prepare-training.ps1").read_text(encoding="utf-8")
    setup_pos = script.index("--profile training-setup run")
    check_start = script.rfind("function Check-Pretrained", 0, setup_pos)
    assert check_start != -1
    guard = script[check_start:setup_pos]
    assert "$cpuImage=Get-TrainingImageName -Device cpu" in guard
    assert "Assert-DockerImage -Image $cpuImage" in guard
    assert "requires the CPU training image" in guard


def test_option_one_does_not_trust_cached_image_probe_before_building() -> None:
    script = (ROOT / "automation" / "powershell" / "prepare-training.ps1").read_text(encoding="utf-8")
    assert "if (Test-TrainingImagePrepared -Device cpu)" not in script
    assert "if (Test-TrainingImagePrepared -Device gpu)" not in script
    assert "if (Test-TrainingImagePrepared -Device gpu-detection)" not in script
    assert script.count("--profile training-build build training-image-") == 3
