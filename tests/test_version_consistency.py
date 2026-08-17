from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_consistent() -> None:
    version = (ROOT / "project" / "VERSION").read_text(encoding="utf-8").strip()
    pyproject = (ROOT / "application" / "pyproject.toml").read_text(encoding="utf-8")
    package_init = (ROOT / "application" / "src" / "isala_ocr" / "__init__.py").read_text(encoding="utf-8")
    compose = (ROOT / "infrastructure" / "docker" / "compose.yaml").read_text(encoding="utf-8")

    assert re.search(rf'^version = "{re.escape(version)}"$', pyproject, re.MULTILINE)
    assert f'__version__ = "{version}"' in package_init
    assert f'image: isalaocr-labeler:{version}' in compose
