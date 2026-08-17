from pathlib import Path

def test_prepare_manifest_permission_is_nonfatal():
    source = Path('automation/training_runtime/paddlex_runner.py').read_text(encoding='utf-8')
    assert 'except PermissionError as exc:' in source
    assert 'optional preparation ' in source
    assert 'payload["manifest_written"] = False' in source
