from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import runpy
import sys
from pathlib import Path
from typing import Iterable

_RUNTIME_DIRECTORY = Path(__file__).resolve().parent
if str(_RUNTIME_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_DIRECTORY))

from isala_numpy_compat import install_numpy_pickle_compatibility


SOURCE_ROOT_DEFAULT = Path("/opt/paddlex-source")
MODEL_DEFAULT = "PP-OCRv6_medium_rec"


def _is_paddleocr_root(path: Path) -> bool:
    # Candidate paths originate from vendor-image environment variables, Python
    # import metadata and bounded filesystem probes. A non-root training user
    # may legitimately be unable to stat one of those locations. Treat that
    # candidate as unavailable instead of aborting discovery with PermissionError.
    try:
        return (
            path.is_dir()
            and (path / "tools" / "train.py").is_file()
            and (path / "ppocr").is_dir()
        )
    except OSError:
        return False


def _resolved_candidates(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        if resolved not in result:
            result.append(resolved)
    return result


def _candidate_paddleocr_roots() -> list[Path]:
    candidates: list[Path] = []

    configured = os.environ.get("PADDLE_PDX_PADDLEOCR_PATH")
    if configured:
        candidates.append(Path(configured))

    # PaddleOCR training images generally expose the ppocr package directly.
    # Its package parent is the repository root that also contains tools/train.py.
    try:
        spec = importlib.util.find_spec("ppocr")
    except (ImportError, ValueError):
        spec = None
    if spec is not None and spec.submodule_search_locations:
        for location in spec.submodule_search_locations:
            package = Path(location)
            candidates.extend([package.parent, package.parent.parent])

    source_root = Path(os.environ.get("ISALA_PADDLEX_SOURCE_ROOT", SOURCE_ROOT_DEFAULT))
    known_roots = [
        source_root,
        Path("/opt"),
        Path("/paddle"),
        Path("/workspace"),
        Path("/root"),
        Path("/usr/local/lib/python3.10/dist-packages"),
    ]
    relative_paths = (
        Path("PaddleOCR"),
        Path("repo_manager/repos/PaddleOCR"),
        Path("paddlex/repo_manager/repos/PaddleOCR"),
        Path("PaddleX/paddlex/repo_manager/repos/PaddleOCR"),
        Path(".paddlex/repos/PaddleOCR"),
        Path(".paddlex/PaddleOCR"),
    )
    for root in known_roots:
        for relative in relative_paths:
            candidates.append(root / relative)
        # Some vendor images place the repository below a versioned or hidden
        # directory. Search only a bounded depth for the canonical train entrypoint.
        for pattern in ("*/tools/train.py", "*/*/tools/train.py", "*/*/*/tools/train.py"):
            try:
                for train_script in root.glob(pattern):
                    candidates.append(train_script.parent.parent)
            except OSError:
                continue

    # Inspect Python import roots using bounded, deterministic relative paths.
    # Avoid an unrestricted recursive filesystem walk in a production container.
    for entry in sys.path:
        if not entry:
            continue
        base = Path(entry)
        for relative in relative_paths:
            candidates.append(base / relative)

    return _resolved_candidates(candidates)


def _find_paddleocr_root() -> tuple[Path, list[Path]]:
    candidates = _candidate_paddleocr_roots()
    for candidate in candidates:
        if _is_paddleocr_root(candidate):
            return candidate, candidates
    rendered = "\n  - ".join(str(path) for path in candidates)
    raise RuntimeError(
        "PaddleOCR training repository was not found in the reusable training image. "
        "A valid root must contain both tools/train.py and the ppocr package. "
        "Checked:\n  - " + rendered
    )


def _register_text_recognition(model: str, source_root: Path, paddleocr_root: Path) -> None:
    # The pinned PaddleX source tree is authoritative. Put it before the legacy
    # base-image package and disable automatic repository initialization: the
    # source distribution does not bundle PaddleOCR's .installed repository,
    # so eager initialization would leave the repository API registry empty.
    source_text = str(source_root)
    if source_text in sys.path:
        sys.path.remove(source_text)
    sys.path.insert(0, source_text)
    os.environ["ISALA_PADDLEX_SOURCE_ROOT"] = source_text
    os.environ["PADDLE_PDX_EAGER_INIT"] = "False"
    os.environ["PADDLE_PDX_PADDLEOCR_PATH"] = str(paddleocr_root)

    importlib.import_module("paddlex")
    importlib.import_module("paddlex.repo_apis.PaddleOCR_api")

    from paddlex.repo_apis.base.register import (
        get_registered_model_info,
        get_registered_suite_info,
    )

    try:
        model_info = get_registered_model_info(model)
    except KeyError as exc:
        raise RuntimeError(
            f"PaddleX repository API bootstrap did not register {model}."
        ) from exc

    suite_info = get_registered_suite_info(model_info["suite"])
    runner_root = Path(str(suite_info["runner_root_path"])).resolve()
    if runner_root != paddleocr_root.resolve():
        raise RuntimeError(
            "PaddleX registered an unexpected PaddleOCR runner root: "
            f"{runner_root}; expected {paddleocr_root.resolve()}"
        )

    print(f"PaddleX registered model: {model}", flush=True)
    print(f"PaddleOCR training repository: {paddleocr_root}", flush=True)
    print(f"PaddleX source bootstrap: {source_root}", flush=True)


def _parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Bootstrap PaddleX repository APIs before executing its CLI"
    )
    parser.add_argument("--main", required=True)
    parser.add_argument("--model", default=MODEL_DEFAULT)
    parser.add_argument("--source-root", default=str(SOURCE_ROOT_DEFAULT))
    args, remaining = parser.parse_known_args(argv)
    return args, remaining


def main(argv: list[str] | None = None) -> int:
    runtime_directory = str(Path(__file__).resolve().parent)
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = os.pathsep.join(
        item for item in (runtime_directory, existing_pythonpath) if item
    )
    install_numpy_pickle_compatibility()

    args, remaining = _parse_args(argv)
    main_path = Path(args.main).resolve()
    source_root = Path(args.source_root).resolve()
    if not main_path.is_file():
        raise FileNotFoundError(f"PaddleX main.py not found: {main_path}")
    if not (source_root / "paddlex").is_dir():
        raise FileNotFoundError(f"PaddleX source package not found: {source_root}")

    paddleocr_root, _ = _find_paddleocr_root()
    _register_text_recognition(args.model, source_root, paddleocr_root)

    sys.argv = [str(main_path), *remaining]
    runpy.run_path(str(main_path), run_name="__main__")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
