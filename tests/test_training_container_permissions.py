from pathlib import Path

import yaml


def test_training_image_runs_as_same_uid_gid_as_runtime_image():
    dockerfile = Path("infrastructure/docker/Dockerfile.training").read_text(encoding="utf-8")
    assert "ARG APP_UID=10001" in dockerfile
    assert "ARG APP_GID=10001" in dockerfile
    assert "USER ${APP_UID}:${APP_GID}" in dockerfile
    assert 'chown -R "${APP_UID}:${APP_GID}"' in dockerfile


def test_compose_aligns_all_paddlex_services_to_uid_10001():
    compose = yaml.safe_load(Path("infrastructure/docker/compose.yaml").read_text(encoding="utf-8"))
    expected_user = "${ISALA_APP_UID:-10001}:${ISALA_APP_GID:-10001}"
    for name in ("training-setup", "trainer-cpu", "trainer-gpu"):
        service = compose["services"][name]
        assert service["user"] == expected_user
        assert "build" not in service
    for name in ("training-image-cpu", "training-image-gpu"):
        args = compose["services"][name]["build"]["args"]
        assert args["APP_UID"] == "${ISALA_APP_UID:-10001}"
        assert args["APP_GID"] == "${ISALA_APP_GID:-10001}"


def test_dictionary_sync_has_actionable_write_probe():
    runner = Path("automation/training_runtime/paddlex_runner.py").read_text(encoding="utf-8")
    assert "def _assert_directory_writable" in runner
    assert "os.getuid()" in runner
    assert "same UID/GID as the dataset builder" in runner
    sync_start = runner.index("def _synchronize_dataset_dictionary")
    sync_end = runner.index("\ndef _charset_report", sync_start)
    assert "_assert_directory_writable(dataset)" in runner[sync_start:sync_end]
