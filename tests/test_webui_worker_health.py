from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_worker_lock_is_not_pid_only():
    text = (ROOT / 'automation/powershell/webui-worker.ps1').read_text(encoding='utf-8')
    assert 'heartbeat_at' in text
    assert 'Get-CimInstance Win32_Process' in text
    assert "webui-worker\\.ps1" in text
    assert 'Test-IsalaWorkerState $old' in text


def test_web_start_waits_for_healthy_worker_and_logs_startup():
    text = (ROOT / 'automation/powershell/label-training-data.ps1').read_text(encoding='utf-8')
    assert 'worker-startup.log' in text
    assert 'worker-startup.err.log' in text
    assert 'AddSeconds(12)' in text
    assert 'The local PowerShell worker did not become healthy' in text
