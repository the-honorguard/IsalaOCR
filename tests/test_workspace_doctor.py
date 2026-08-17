from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_doctor():
    path = ROOT / "automation" / "training_runtime" / "workspace_doctor.py"
    spec = spec_from_file_location("workspace_doctor", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_doctor_has_read_write_and_repair_modes() -> None:
    doctor = load_doctor()
    assert doctor.READABLE_DIRECTORIES
    assert doctor.WRITABLE_DIRECTORIES
    assert callable(doctor.check)
    assert callable(doctor.repair)


def test_compose_has_non_root_check_and_root_repair_services() -> None:
    compose = yaml.safe_load((ROOT / "infrastructure" / "docker" / "compose.yaml").read_text())
    check = compose["services"]["workspace-doctor"]
    repair = compose["services"]["workspace-repair"]
    assert check["user"] == "${ISALA_APP_UID:-10001}:${ISALA_APP_GID:-10001}"
    assert repair["user"] == "0:0"
    assert "CHOWN" in repair["cap_add"]
    assert check["entrypoint"] == ["python3", "/opt/isala-training/workspace_doctor.py"]
