from pathlib import Path
from types import SimpleNamespace

import isala_ocr.cli as cli


def _config(workspace: Path):
    return SimpleNamespace(
        raw={
            "training": {"workspace": str(workspace)},
            "ocr": {"active_recognition_model_dir": "/models/active-recognition"},
        }
    )


def test_localization_workspace_does_not_initialize_recognition_models(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = _config(workspace)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("localization-only workspace must not touch /models")

    monkeypatch.setattr(cli, "project_active_recognition_dir", fail_if_called)

    resolved = cli._localization_workspace(config, str(workspace))

    assert resolved == workspace.resolve()
    assert config.raw["ocr"]["active_recognition_model_dir"] == "/models/active-recognition"


def test_recognition_workspace_keeps_project_active_model_setup(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = _config(workspace)
    expected = Path("/models/projects/test-project/active-recognition")
    calls = []

    def fake_project_dir(models_root, workspace_root):
        calls.append((Path(models_root), Path(workspace_root)))
        return expected

    monkeypatch.setattr(cli, "project_active_recognition_dir", fake_project_dir)

    resolved = cli._training_workspace(config, str(workspace))

    assert resolved == workspace.resolve()
    assert calls == [(Path("/models"), workspace)]
    assert config.raw["ocr"]["active_recognition_model_dir"] == str(expected)


def test_dataset_build_command_uses_readonly_localization_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = _config(workspace)
    captured = {}

    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    monkeypatch.setattr(
        cli,
        "project_active_recognition_dir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dataset build must not initialize /models/projects")
        ),
    )
    def fake_build(path):
        captured["workspace"] = Path(path)
        return {"status": "ok"}

    monkeypatch.setattr(cli, "build_localization_dataset", fake_build)
    args = SimpleNamespace(config="ignored.yaml", workspace=str(workspace))

    assert cli._build_localization_dataset_cmd(args) == 0
    assert captured["workspace"] == workspace.resolve()
