from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_precreates_writable_paddle_cache_without_recursive_chown() -> None:
    dockerfile = (ROOT / "infrastructure" / "docker" / "Dockerfile.runtime").read_text(encoding="utf-8")

    assert 'chown -R "${APP_UID}:${APP_GID}" /output /models /training /tmp' not in dockerfile
    assert 'XDG_CACHE_HOME=/tmp/.cache' in dockerfile
    assert '/tmp/.cache' in dockerfile
    assert '/tmp/.cache/paddle' in dockerfile
    assert 'install -d -o "${APP_UID}" -g "${APP_GID}"' in dockerfile
