from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import uuid
from pathlib import Path
from typing import Any

READABLE_DIRECTORIES = (Path('/input'),)
WRITABLE_DIRECTORIES = (
    Path('/output'),
    Path('/models'),
    Path('/models/training'),
    Path('/models/projects'),
    Path('/training'),
    Path('/training/workspace'),
    Path('/training/workspace/projects'),
    Path('/training/registry'),
    Path('/training/registry/projects'),
)


def _active_project_id() -> str:
    explicit = str(os.environ.get('ISALA_PROJECT_ID', '')).strip()
    if explicit:
        return explicit
    pointer = Path('/training/workspace/active_project.json')
    try:
        if pointer.is_file():
            payload = json.loads(pointer.read_text(encoding='utf-8'))
            value = str(payload.get('project_id', '')).strip()
            if value:
                return value
    except (OSError, ValueError, TypeError):
        pass
    return 'cmr_testcase_01'


def _writable_directories() -> tuple[Path, ...]:
    project_id = _active_project_id()
    project_workspace = Path('/training/workspace/projects') / project_id
    project_registry = Path('/training/registry/projects') / project_id
    project_active_recognition = Path('/models/projects') / project_id / 'active-recognition'
    return WRITABLE_DIRECTORIES + (
        project_active_recognition,
        project_workspace,
        project_workspace / 'crops',
        project_workspace / 'datasets',
        project_workspace / 'runs',
        project_workspace / 'diagnostics',
        project_registry,
    )


def _result(path: Path, operation: str, status: str, message: str) -> dict[str, str]:
    return {
        'path': str(path),
        'operation': operation,
        'status': status,
        'message': message,
    }


def _test_readable(path: Path) -> dict[str, str]:
    try:
        if not path.is_dir():
            return _result(path, 'read', 'fail', 'directory does not exist')
        next(path.iterdir(), None)
        return _result(path, 'read', 'pass', 'directory is readable')
    except PermissionError as exc:
        return _result(path, 'read', 'fail', f'permission denied: {exc}')
    except OSError as exc:
        return _result(path, 'read', 'fail', f'OS error: {exc}')


def _test_writable(path: Path) -> dict[str, str]:
    probe = path / f'.isalaocr-write-probe-{os.getpid()}-{uuid.uuid4().hex}'
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text('permission probe', encoding='utf-8')
        probe.unlink()
        return _result(path, 'write', 'pass', 'directory is writable')
    except PermissionError as exc:
        return _result(path, 'write', 'fail', f'permission denied: {exc}')
    except OSError as exc:
        return _result(path, 'write', 'fail', f'OS error: {exc}')
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass


def _repair_tree(path: Path, uid: int, gid: int) -> dict[str, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        for current_root, directories, files in os.walk(path):
            current = Path(current_root)
            os.chown(current, uid, gid)
            current.chmod(current.stat().st_mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            for name in directories:
                child = current / name
                os.chown(child, uid, gid)
                child.chmod(child.stat().st_mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            for name in files:
                child = current / name
                os.chown(child, uid, gid)
                child.chmod(child.stat().st_mode | stat.S_IRUSR | stat.S_IWUSR)
        return _result(path, 'repair', 'pass', f'ownership set to {uid}:{gid}; owner write access ensured')
    except PermissionError as exc:
        return _result(path, 'repair', 'fail', f'permission denied: {exc}')
    except OSError as exc:
        return _result(path, 'repair', 'fail', f'OS error: {exc}')


def check() -> dict[str, Any]:
    checks = [_test_readable(path) for path in READABLE_DIRECTORIES]
    checks.extend(_test_writable(path) for path in _writable_directories())
    failures = [item for item in checks if item['status'] == 'fail']
    return {
        'mode': 'check',
        'uid': os.geteuid(),
        'gid': os.getegid(),
        'checks': checks,
        'passed': not failures,
        'failure_count': len(failures),
    }


def repair() -> dict[str, Any]:
    if os.geteuid() != 0:
        return {
            'mode': 'repair',
            'uid': os.geteuid(),
            'gid': os.getegid(),
            'checks': [],
            'passed': False,
            'failure_count': 1,
            'error': 'repair mode must run as root',
        }
    uid = int(os.environ.get('ISALA_APP_UID', '10001'))
    gid = int(os.environ.get('ISALA_APP_GID', '10001'))
    project_id = _active_project_id()
    repair_targets = (
        Path('/output'),
        Path('/models/training'),
        Path('/models/projects') / project_id / 'active-recognition',
        Path('/training/workspace'),
        Path('/training/workspace/projects') / project_id,
        Path('/training/registry'),
        Path('/training/registry/projects') / project_id,
    )
    checks = [_repair_tree(path, uid, gid) for path in repair_targets]
    failures = [item for item in checks if item['status'] == 'fail']
    return {
        'mode': 'repair',
        'uid': os.geteuid(),
        'gid': os.getegid(),
        'target_uid': uid,
        'target_gid': gid,
        'checks': checks,
        'passed': not failures,
        'failure_count': len(failures),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Check or repair IsalaOCR bind-mount permissions.')
    parser.add_argument('mode', choices=('check', 'repair'))
    parser.add_argument('--json', action='store_true', dest='as_json')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = check() if args.mode == 'check' else repair()
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for item in payload.get('checks', []):
            print(f"[{item['status'].upper()}] {item['operation']} {item['path']}: {item['message']}")
        if payload.get('error'):
            print(payload['error'], file=sys.stderr)
    return 0 if payload.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
