from __future__ import annotations

import argparse
import hashlib
import json
import os
import importlib.metadata
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

_RUNTIME_DIRECTORY = Path(__file__).resolve().parent
if str(_RUNTIME_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_DIRECTORY))

from isala_numpy_compat import install_numpy_pickle_compatibility
from training_progress import TrainingProgressRenderer

NUMPY_PICKLE_COMPATIBILITY_ACTIVE = install_numpy_pickle_compatibility()

PRETRAIN_URLS = {
    "PicoDet-S": "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_pretrained_model/PicoDet-S_pretrained.pdparams",
    "RT-DETR-L_wireless_table_cell_det": "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_pretrained_model/RT-DETR-L_wireless_table_cell_det_pretrained.pdparams",
    "PP-OCRv6_medium_rec": "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_pretrained_model/PP-OCRv6_medium_rec_pretrained.pdparams",
    "PP-OCRv6_small_rec": "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_pretrained_model/PP-OCRv6_small_rec_pretrained.pdparams",
    "PP-OCRv6_tiny_rec": "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_pretrained_model/PP-OCRv6_tiny_rec_pretrained.pdparams",
}

BUNDLED_DICTIONARY_ENV = "ISALA_PPOCRV6_DICTIONARY"
BUNDLED_DICTIONARY_DEFAULT = "/opt/isala-training-resources/ppocrv6_dict.txt"
MODEL_USE_SPACE_DEFAULTS = {
    "PP-OCRv6_medium_rec": True,
    "PP-OCRv6_small_rec": True,
    "PP-OCRv6_tiny_rec": True,
}


def _candidate_roots() -> list[Path]:
    configured_source = Path(os.environ.get("ISALA_PADDLEX_SOURCE_ROOT", "/opt/paddlex-source"))
    roots = [
        configured_source,
        Path("/paddle"),
        Path("/workspace"),
        Path("/opt"),
        Path("/root"),
    ]
    try:
        import paddlex

        package = Path(paddlex.__file__).resolve()
        roots.extend([package.parent, package.parent.parent, package.parent.parent.parent])
    except Exception:
        pass
    result = []
    for root in roots:
        if root.exists() and root not in result:
            result.append(root)
    return result


def _discover(model: str) -> tuple[Path, Path]:
    config_names = [f"{model}.yaml", f"{model}.yml"]
    main_candidates: list[Path] = []
    config_candidates: list[Path] = []
    for root in _candidate_roots():
        for config_name in config_names:
            config_candidates.extend(root.glob(f"**/configs/modules/text_recognition/{config_name}"))
        for candidate in root.glob("**/main.py"):
            if (candidate.parent / "paddlex" / "configs").is_dir():
                main_candidates.append(candidate)
    config_candidates = sorted(
        set(path.resolve() for path in config_candidates),
        key=lambda path: (len(path.parts), len(str(path)), str(path)),
    )
    main_candidates = sorted(
        set(path.resolve() for path in main_candidates),
        key=lambda path: (len(path.parts), len(str(path)), str(path)),
    )
    if not config_candidates:
        try:
            installed_version = importlib.metadata.version("paddlex")
        except importlib.metadata.PackageNotFoundError:
            installed_version = "not installed"
        searched = ", ".join(str(path) for path in _candidate_roots())
        raise FileNotFoundError(
            f"PaddleX configuration for {model} was not found. "
            f"Installed PaddleX version: {installed_version}. "
            "PP-OCRv6 training requires a PP-OCRv6-capable PaddleX source release "
            "(IsalaOCR pins 3.7.2). Rebuild the training image with menu option 1. "
            f"Searched roots: {searched}"
        )
    config = config_candidates[0]
    main = next(
        (item for item in main_candidates if config.is_relative_to(item.parent)),
        main_candidates[0] if main_candidates else None,
    )
    if main is None:
        raise FileNotFoundError("Could not locate PaddleX main.py in the training image")
    return main, config


def _walk_key(value: Any, key: str) -> Iterable[Any]:
    if isinstance(value, dict):
        for current_key, current_value in value.items():
            if current_key == key:
                yield current_value
            yield from _walk_key(current_value, key)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_key(item, key)


def _path_sort_key(path: Path) -> tuple[int, int, str]:
    resolved = path.resolve()
    return (len(resolved.parts), len(str(resolved)), str(resolved))


def _resolve_path_from_roots(candidate: Path, roots: list[Path]) -> Path | None:
    direct_candidates: list[Path] = [candidate]
    if not candidate.is_absolute():
        for root in roots:
            direct_candidates.extend(
                [
                    root / candidate,
                    root / "PaddleOCR" / candidate,
                    root / "paddleocr" / candidate,
                    root / "paddlex" / "repo_apis" / "PaddleOCR_api" / candidate,
                ]
            )
    for item in direct_candidates:
        resolved = item.resolve()
        if resolved.is_file():
            return resolved

    # The official PaddleX image may store the PaddleOCR checkout under a
    # versioned repository-manager directory. Search by the unique dictionary
    # basename and prefer candidates whose trailing path matches the configured
    # relative path.
    matches: list[Path] = []
    for root in roots:
        try:
            matches.extend(path for path in root.glob(f"**/{candidate.name}") if path.is_file())
        except OSError:
            continue
    candidate_parts = tuple(candidate.parts)
    ranked = sorted(
        set(path.resolve() for path in matches),
        key=lambda path: (
            0 if tuple(path.parts[-len(candidate_parts):]) == candidate_parts else 1,
            *_path_sort_key(path),
        ),
    )
    return ranked[0] if ranked else None


def _official_model_config_candidates(model: str, high_level_config: Path) -> list[Path]:
    names = [f"{model}.yaml", f"{model}.yml"]
    candidates: list[Path] = []
    for root in _candidate_roots():
        for name in names:
            candidates.extend(root.glob(f"**/repo_apis/PaddleOCR_api/configs/{name}"))
            candidates.extend(root.glob(f"**/configs/rec/**/{name}"))
    # A caller may supply a low-level config directly during tests or custom use.
    candidates.append(high_level_config)
    return sorted(set(path.resolve() for path in candidates if path.is_file()), key=_path_sort_key)


def _resolve_dictionary(config_path: Path, model: str) -> tuple[Path, bool, Path]:
    roots = _candidate_roots()
    searched_configs: list[str] = []
    dictionary_references: list[tuple[Path, Path]] = []
    use_space = MODEL_USE_SPACE_DEFAULTS.get(model, False)
    selected_model_config = config_path.resolve()

    for model_config in _official_model_config_candidates(model, config_path):
        searched_configs.append(str(model_config))
        raw = yaml.safe_load(model_config.read_text(encoding="utf-8")) or {}
        dictionary_values = [value for value in _walk_key(raw, "character_dict_path") if value]
        use_space_values = list(_walk_key(raw, "use_space_char"))
        if use_space_values:
            use_space = any(bool(value) for value in use_space_values)
        if dictionary_values:
            selected_model_config = model_config
            dictionary_references.extend(
                (Path(str(value)), model_config) for value in dictionary_values
            )

    # The PaddleX sdist references a dictionary from the separate PaddleOCR
    # repository. IsalaOCR therefore bakes the pinned official dictionary into
    # a deterministic image path instead of expecting repository-manager
    # internals or a runtime network connection.
    bundled = Path(
        os.environ.get(BUNDLED_DICTIONARY_ENV, BUNDLED_DICTIONARY_DEFAULT)
    ).expanduser()
    if bundled.is_file():
        return bundled.resolve(), use_space, selected_model_config.resolve()

    # Compatibility path for development fixtures and older images that do
    # contain a full PaddleOCR checkout.
    for candidate, model_config in dictionary_references:
        dictionary = _resolve_path_from_roots(candidate, roots + [model_config.parent])
        if dictionary is not None:
            return dictionary, use_space, model_config

    raise FileNotFoundError(
        f"Official character dictionary for {model} was not found in the training image. "
        f"Expected bundled dictionary: {bundled}. "
        f"Searched model configs: {', '.join(searched_configs) or 'none'}. "
        "Install the current IsalaOCR codebase and rebuild the training image; "
        "the dictionary is downloaded and cryptographically pinned during the Docker build."
    )


def _dataset_label_files(dataset: Path) -> list[Path]:
    return [dataset / name for name in ("train.txt", "val.txt", "test.txt") if (dataset / name).is_file()]


def _dataset_characters(dataset: Path) -> set[str]:
    characters: set[str] = set()
    for path in _dataset_label_files(dataset):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            if "\t" not in line:
                raise ValueError(
                    f"Invalid recognition annotation in {path}:{line_number}; expected image path and exact label separated by a tab"
                )
            _, label = line.split("\t", 1)
            characters.update(label)
    return characters


def _assert_directory_writable(directory: Path) -> None:
    """Fail early when a bind-mounted training directory uses a different UID/GID."""
    probe = directory / f".isalaocr-write-probe-{os.getpid()}"
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        raise PermissionError(
            f"Training workspace is not writable by container UID/GID "
            f"{os.getuid()}:{os.getgid()}: {directory}. "
            "The PaddleX trainer must run with the same UID/GID as the dataset builder "
            "(IsalaOCR default 10001:10001). Install v3.3.3 or newer and rebuild the "
            "training image; do not delete the reviewed dataset."
        ) from exc


def _synchronize_dataset_dictionary(
    dataset: Path, config: Path, model: str
) -> dict[str, Any]:
    if not dataset.is_dir():
        raise FileNotFoundError(f"Dataset directory not found: {dataset}")
    _assert_directory_writable(dataset)
    required = [dataset / "train.txt", dataset / "val.txt"]
    missing_files = [str(path) for path in required if not path.is_file()]
    if missing_files:
        raise FileNotFoundError(
            "PaddleX recognition dataset is incomplete; missing: " + ", ".join(missing_files)
        )

    official_dictionary, use_space, model_config = _resolve_dictionary(config, model)
    official_bytes = official_dictionary.read_bytes()
    supported = set(official_dictionary.read_text(encoding="utf-8").splitlines())
    if use_space:
        supported.add(" ")
    dataset_characters = _dataset_characters(dataset)
    unsupported = sorted(dataset_characters - supported)
    if unsupported:
        rendered = ", ".join(repr(char) for char in unsupported)
        raise ValueError(
            f"Exact labels contain characters unsupported by the official {model} dictionary: {rendered}"
        )

    dataset_dictionary = dataset / "dict.txt"
    changed = not dataset_dictionary.is_file() or dataset_dictionary.read_bytes() != official_bytes
    if changed:
        dataset_dictionary.write_bytes(official_bytes)
        print(
            f"Synchronized PaddleX dictionary: {dataset_dictionary} <- {official_dictionary}",
            flush=True,
        )

    manifest = {
        "model": model,
        "model_config": str(model_config),
        "official_dictionary": str(official_dictionary),
        "dataset_dictionary": str(dataset_dictionary),
        "sha256": hashlib.sha256(official_bytes).hexdigest(),
        "dictionary_entries": len(official_dictionary.read_text(encoding="utf-8").splitlines()),
        "use_space_char": use_space,
        "labels_preserved_verbatim": True,
        "changed": changed,
    }
    (dataset / "dictionary_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def _charset_report(dataset: Path, config: Path, model: str, output: Path) -> dict[str, Any]:
    dictionary, use_space, model_config = _resolve_dictionary(config, model)
    dataset_chars = _dataset_characters(dataset)
    supported = set(dictionary.read_text(encoding="utf-8").splitlines())
    if use_space:
        supported.add(" ")
    missing = sorted(dataset_chars - supported)
    status = "ok" if not missing else "unsupported_characters"
    report = {
        "status": status,
        "dataset": str(dataset),
        "model": model,
        "model_config": str(model_config),
        "dictionary": str(dictionary),
        "use_space_char": use_space,
        "dataset_characters": sorted(dataset_chars),
        "unsupported_characters": missing,
        "note": "Labels are checked verbatim; no character substitution or normalization is performed.",
    }
    output.mkdir(parents=True, exist_ok=True)
    _assert_directory_writable(output)
    (output / "charset_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def _build_paddlex_command(
    main: Path, config: Path, model: str, overrides: list[str]
) -> list[str]:
    bootstrap = Path(__file__).resolve().with_name("paddlex_bootstrap.py")
    if not bootstrap.is_file():
        raise FileNotFoundError(f"PaddleX bootstrap script not found: {bootstrap}")
    command = [
        sys.executable,
        str(bootstrap),
        "--main",
        str(main),
        "--model",
        model,
        "--source-root",
        str(main.parent),
        "-c",
        str(config),
    ]
    for override in overrides:
        command.extend(["-o", override])
    return command


def _run_paddlex(
    main: Path,
    config: Path,
    model: str,
    overrides: list[str],
    *,
    progress: TrainingProgressRenderer | None = None,
) -> None:
    command = _build_paddlex_command(main, config, model, overrides)
    environment = os.environ.copy()
    runtime_directory = str(Path(__file__).resolve().parent)
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (runtime_directory, existing_pythonpath) if item
    )
    if progress is None:
        print("Executing:", " ".join(command), flush=True)
        subprocess.run(command, check=True, env=environment)
        return

    progress.record_command(command)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=environment,
    )
    try:
        assert process.stdout is not None
        for line in process.stdout:
            progress.feed(line)
        return_code = process.wait()
        progress.finish(return_code)
    except BaseException:
        process.kill()
        process.wait()
        try:
            progress.finish(process.returncode if process.returncode is not None else 130)
        except Exception:
            progress.close()
        raise
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command)


def _training_weight_path(model: str, pretrain_root: str | Path) -> Path:
    return Path(pretrain_root) / f"{model}_pretrained.pdparams"


def _is_cached_weight_ready(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 1024 * 1024
    except OSError:
        return False


def _open_pretrain_url(url: str, *, timeout: int = 30):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "IsalaOCR/3.4.8",
            "Range": "bytes=0-0",
        },
    )
    return urllib.request.urlopen(request, timeout=timeout)


def probe_pretrain(args: argparse.Namespace) -> int:
    url = PRETRAIN_URLS[args.model]
    try:
        with _open_pretrain_url(url, timeout=args.timeout) as response:
            response.read(1)
            status = getattr(response, "status", None)
            final_url = getattr(response, "url", url)
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError(
            "The network-enabled model preparation container cannot reach the "
            f"official pretrained-weight source: {url} ({exc})"
        ) from exc
    print(json.dumps({
        "model": args.model,
        "source": url,
        "final_url": final_url,
        "http_status": status,
        "reachable": True,
    }, indent=2))
    return 0


def _download(url: str, destination: Path) -> None:
    if _is_cached_weight_ready(destination):
        print(f"Using cached file: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    print(f"Downloading {url} -> {destination}")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
    except (OSError, urllib.error.URLError) as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            "Downloading the official pretrained weight failed. The download is "
            f"performed by the network-enabled model-prep service: {url} ({exc})"
        ) from exc
    if not _is_cached_weight_ready(temporary):
        size = temporary.stat().st_size if temporary.exists() else 0
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"Downloaded pretrained weight is unexpectedly small ({size} bytes): {url}"
        )
    temporary.replace(destination)


def download_pretrain(args: argparse.Namespace) -> int:
    if args.model not in PRETRAIN_URLS:
        raise ValueError(f"No official pretrain URL configured for {args.model}")
    destination = _training_weight_path(args.model, args.pretrain_root)
    _download(PRETRAIN_URLS[args.model], destination)
    print(json.dumps({
        "model": args.model,
        "pretrained_weight": str(destination),
        "bytes": destination.stat().st_size,
        "cached": True,
    }, indent=2))
    return 0


def prepare(args: argparse.Namespace) -> int:
    if args.model not in PRETRAIN_URLS:
        raise ValueError(f"No official pretrain URL configured for {args.model}")

    # Verify the training source before claiming preparation succeeded.
    main, config = _discover(args.model)
    pretrain = _training_weight_path(args.model, args.pretrain_root)
    if args.offline:
        if not _is_cached_weight_ready(pretrain):
            raise FileNotFoundError(
                "Offline training preparation requires the pretrained weight to "
                f"already exist and exceed 1 MiB: {pretrain}. Run the dedicated "
                "network-enabled pretrain download step first."
            )
        print(f"Using cached file: {pretrain}")
    else:
        _download(PRETRAIN_URLS[args.model], pretrain)
    # Inference models are prepared by the runtime image through the model-prep
    # service before this training-only container is started. The official
    # PaddleX training image does not necessarily include the paddleocr Python
    # package, so it must not report an unsuccessful PaddleOCR import as a
    # successful inference-cache initialization.
    model_cache = Path(args.model_cache)
    model_cache.mkdir(parents=True, exist_ok=True)
    payload = {
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "pretrained_weight": str(pretrain),
        "model_cache": str(model_cache),
        "paddlex_main": str(main),
        "paddlex_config": str(config),
        "inference_cache_prepared_separately": True,
    }
    manifest = Path(args.pretrain_root) / "training_prepare_manifest.json"
    rendered = json.dumps(payload, indent=2)
    try:
        manifest.write_text(rendered, encoding="utf-8")
    except PermissionError as exc:
        # The pretrained weight may have been created by an older root-running
        # container on a Windows bind mount. The weight itself is the required
        # artifact; this JSON file is diagnostic metadata only. Do not fail a
        # valid cached preparation solely because the legacy directory blocks
        # non-root metadata writes.
        print(
            "WARNING: pretrained weight is ready, but the optional preparation "
            f"manifest could not be written: {manifest} ({exc})"
        )
        payload["manifest_written"] = False
        payload["manifest_error"] = str(exc)
    else:
        payload["manifest_written"] = True
    print(json.dumps(payload, indent=2))
    return 0


def _verify_paddle_runtime(device: str) -> dict[str, Any]:
    """Import PaddlePaddle only after the container has started.

    GPU driver libraries such as libcuda.so.1 are injected by the NVIDIA
    container runtime and are not available during a normal Docker build.
    """
    try:
        import paddle
    except ImportError as exc:
        detail = str(exc)
        if device.lower().startswith("gpu") and "libcuda.so.1" in detail:
            raise RuntimeError(
                "The GPU training container started without the NVIDIA driver runtime "
                "(libcuda.so.1 is unavailable). Verify Docker Desktop GPU support, "
                "the NVIDIA driver and the trainer-gpu 'gpus: all' setting."
            ) from exc
        raise RuntimeError(f"PaddlePaddle could not be imported at container runtime: {detail}") from exc

    version = str(getattr(paddle, "__version__", "unknown"))
    result: dict[str, Any] = {"version": version, "device": device}
    if device.lower().startswith("gpu"):
        compiled_with_cuda = bool(
            getattr(paddle, "is_compiled_with_cuda", lambda: False)()
        )
        cuda_module = getattr(getattr(paddle, "device", None), "cuda", None)
        device_count = int(
            getattr(cuda_module, "device_count", lambda: 0)() if cuda_module else 0
        )
        result.update(
            {
                "compiled_with_cuda": compiled_with_cuda,
                "cuda_device_count": device_count,
            }
        )
        if not compiled_with_cuda:
            raise RuntimeError(
                f"Installed PaddlePaddle {version} is not CUDA-enabled inside trainer-gpu."
            )
        if device_count < 1:
            raise RuntimeError(
                "No CUDA device is visible inside trainer-gpu. Verify Docker Desktop "
                "GPU support and the NVIDIA driver before retrying GPU training."
            )
    print("PaddlePaddle runtime verification:", json.dumps(result, sort_keys=True))
    return result


def _verify_numpy_pickle_runtime() -> dict[str, str | bool]:
    """Verify that NumPy 2-created Paddle weight pickles can be imported."""
    import importlib

    try:
        import numpy

        multiarray = importlib.import_module("numpy._core.multiarray")
        reconstruct = getattr(multiarray, "_reconstruct")
    except Exception as exc:  # noqa: BLE001 - collapse dependency detail into one fix
        raise RuntimeError(
            "The training runtime cannot resolve numpy._core.multiarray while loading "
            "the official PaddleOCR pretrained weights. Install IsalaOCR v3.4.7 or "
            "newer. This is a runtime-script repair; rebuilding the training images "
            "is not required."
        ) from exc
    if not callable(reconstruct):
        raise RuntimeError("NumPy pickle compatibility resolved a non-callable _reconstruct API.")
    result: dict[str, str | bool] = {
        "numpy_version": str(getattr(numpy, "__version__", "unknown")),
        "numpy_core_module": str(getattr(multiarray, "__file__", "unknown")),
        "compatibility_alias_active": NUMPY_PICKLE_COMPATIBILITY_ACTIVE,
    }
    print("NumPy pickle compatibility:", json.dumps(result, sort_keys=True))
    return result


def _verify_shapely_runtime() -> dict[str, str]:
    """Verify the Shapely API required by the pinned PaddleOCR source."""
    try:
        import shapely
        from shapely import intersection
    except Exception as exc:  # noqa: BLE001 - convert dependency failures to one diagnostic
        raise RuntimeError(
            "The training image has an incompatible Shapely runtime. "
            "PaddleOCR requires Shapely 2.x with top-level intersection support. "
            "Run menu option 1 to build training image revision 3.8.5."
        ) from exc
    if not callable(intersection):
        raise RuntimeError(
            "The installed Shapely package does not expose a callable top-level intersection API. "
            "Run menu option 1 to rebuild the training images."
        )
    result = {
        "version": str(getattr(shapely, "__version__", "unknown")),
        "module": str(getattr(shapely, "__file__", "unknown")),
    }
    print("Shapely runtime verification:", json.dumps(result, sort_keys=True))
    return result


def _verify_paddledet_runtime() -> dict[str, Any]:
    """Import the exact legacy dependencies used by PaddleDetection training.

    The training subprocess inherits this runtime directory on PYTHONPATH.
    Therefore the IsalaOCR pkg_resources compatibility module is tested here
    with the same import resolution that tools/train.py receives.
    """
    compatibility_directory = Path(__file__).resolve().parent / "paddledet_compat"
    compatibility_text = str(compatibility_directory)
    if compatibility_text not in sys.path:
        sys.path.insert(0, compatibility_text)
    try:
        import importlib.metadata
        import pkg_resources
        import ppdet
        # PaddleDetection model_zoo is the module that still imports and uses
        # pkg_resources. Import it explicitly; importing only ppdet can miss a
        # lazy failure on some repository revisions.
        import ppdet.model_zoo.model_zoo as model_zoo
    except Exception as exc:  # noqa: BLE001 - collapse dependency failures into one diagnostic
        raise RuntimeError(
            "PaddleDetection training runtime is incomplete: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    result = {
        "version": importlib.metadata.version("paddledet"),
        "module": str(getattr(ppdet, "__file__", "unknown")),
        "model_zoo": str(getattr(model_zoo, "__file__", "unknown")),
        "pkg_resources": str(getattr(pkg_resources, "__file__", "unknown")),
        "pkg_resources_compat": bool(getattr(pkg_resources, "__isala_compat__", False)),
    }
    print("PaddleDetection runtime verification:", json.dumps(result, sort_keys=True))
    return result


def runtime_check(args: argparse.Namespace) -> int:
    """Verify training dependencies without touching datasets."""
    result = _verify_paddle_runtime(args.device)
    result["numpy_pickle"] = _verify_numpy_pickle_runtime()
    result["shapely"] = _verify_shapely_runtime()
    if getattr(args, "require_paddledet", False):
        result["paddledet"] = _verify_paddledet_runtime()
    print(json.dumps(result, sort_keys=True))
    return 0


def check(args: argparse.Namespace) -> int:
    main, config = _discover(args.model)
    dataset = Path(args.dataset)
    _synchronize_dataset_dictionary(dataset, config, args.model)
    report = _charset_report(dataset, config, args.model, Path(args.output))
    if report["unsupported_characters"]:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 3
    _run_paddlex(
        main,
        config,
        args.model,
        [
            "Global.mode=check_dataset",
            f"Global.dataset_dir={dataset}",
            f"Global.output={args.output}",
        ],
    )
    return 0


def train(args: argparse.Namespace) -> int:
    _verify_paddle_runtime(args.device)
    _verify_numpy_pickle_runtime()
    _verify_shapely_runtime()
    # Object-detection training must prove that PaddleDetection's legacy
    # model-zoo dependency can be imported before launching the nested
    # tools/train.py subprocess. This turns a cryptic child-process traceback
    # into an immediate, actionable runtime check.
    if args.model == "PicoDet-S":
        _verify_paddledet_runtime()
    main, config = _discover(args.model)
    dataset = Path(args.dataset)
    _synchronize_dataset_dictionary(dataset, config, args.model)
    output = Path(args.output)
    report = _charset_report(dataset, config, args.model, output)
    if report["unsupported_characters"]:
        print(
            "Training blocked because exact labels contain characters absent from the official model dictionary.",
            file=sys.stderr,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False), file=sys.stderr)
        return 3
    pretrain = Path(args.pretrain or Path(args.pretrain_root) / f"{args.model}_pretrained.pdparams")
    if not pretrain.is_file():
        raise FileNotFoundError(
            f"Pretrained weights not found: {pretrain}. Run prepare-training first."
        )
    overrides = [
        "Global.mode=train",
        f"Global.dataset_dir={dataset}",
        f"Global.device={args.device}",
        f"Global.output={output}",
        f"Train.epochs_iters={args.epochs}",
        f"Train.batch_size={args.batch_size}",
        f"Train.learning_rate={args.learning_rate}",
        f"Train.pretrain_weight_path={pretrain}",
        f"Train.log_interval={args.log_interval}",
        # PaddleOCR still enables the removed VisualDL integration in some
        # shipped recognition configs. IsalaOCR has its own live/run logging.
        "Global.use_visualdl=False",
    ]
    if args.resume:
        overrides.append(f"Train.resume_path={args.resume}")
    if args.dy2st:
        overrides.append("Train.dy2st=True")
    progress = TrainingProgressRenderer(
        output,
        args.epochs,
        # The queue stores the logical device (cpu/gpu), while PaddleX may
        # receive an indexed device such as gpu:0. Keep the progress payload
        # on the same logical namespace used by the WebUI job cards.
        device="gpu" if str(args.device).lower().startswith("gpu") else "cpu",
        verbose=args.detailed_output,
    )
    _run_paddlex(main, config, args.model, overrides, progress=progress)
    return 0


def evaluate(args: argparse.Namespace) -> int:
    _verify_paddle_runtime(args.device)
    _verify_numpy_pickle_runtime()
    main, config = _discover(args.model)
    _synchronize_dataset_dictionary(Path(args.dataset), config, args.model)
    _run_paddlex(
        main,
        config,
        args.model,
        [
            "Global.mode=evaluate",
            f"Global.dataset_dir={args.dataset}",
            f"Global.device={args.device}",
            f"Global.output={args.output}",
            f"Evaluate.weight_path={args.weight}",
        ],
    )
    return 0


def export(args: argparse.Namespace) -> int:
    _verify_paddle_runtime(args.device)
    _verify_numpy_pickle_runtime()
    main, config = _discover(args.model)
    _run_paddlex(
        main,
        config,
        args.model,
        [
            "Global.mode=export",
            f"Global.device={args.device}",
            f"Global.output={args.output}",
            f"Export.weight_path={args.weight}",
        ],
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="IsalaOCR PaddleX training runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe-pretrain")
    probe.add_argument("--model", default="PP-OCRv6_medium_rec", choices=sorted(PRETRAIN_URLS))
    probe.add_argument("--timeout", type=int, default=30)
    probe.set_defaults(func=probe_pretrain)

    download = sub.add_parser("download-pretrain")
    download.add_argument("--model", default="PP-OCRv6_medium_rec", choices=sorted(PRETRAIN_URLS))
    download.add_argument("--pretrain-root", default="/models/training")
    download.set_defaults(func=download_pretrain)

    prep = sub.add_parser("prepare")
    prep.add_argument("--model", default="PP-OCRv6_medium_rec", choices=sorted(PRETRAIN_URLS))
    prep.add_argument("--pretrain-root", default="/models/training")
    prep.add_argument("--model-cache", default="/models/paddlex")
    prep.add_argument("--offline", action="store_true")
    prep.set_defaults(func=prepare)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--model", default="PP-OCRv6_medium_rec", choices=sorted(PRETRAIN_URLS))
    common.add_argument("--dataset", required=True)
    common.add_argument("--output", required=True)

    runtime_parser = sub.add_parser("runtime-check")
    runtime_parser.add_argument("--device", default="gpu:0")
    runtime_parser.add_argument(
        "--require-paddledet",
        action="store_true",
        help="Also import the installed PaddleDetection package in the started container.",
    )
    runtime_parser.set_defaults(func=runtime_check)

    check_parser = sub.add_parser("check", parents=[common])
    check_parser.set_defaults(func=check)

    train_parser = sub.add_parser("train", parents=[common])
    train_parser.add_argument("--device", default="gpu:0")
    train_parser.add_argument("--epochs", type=int, default=50)
    train_parser.add_argument("--batch-size", type=int, default=32)
    train_parser.add_argument("--learning-rate", type=float, default=0.0001)
    train_parser.add_argument("--pretrain")
    train_parser.add_argument("--pretrain-root", default="/models/training")
    train_parser.add_argument("--resume")
    train_parser.add_argument("--log-interval", type=int, default=10)
    train_parser.add_argument("--dy2st", action="store_true")
    train_parser.add_argument(
        "--detailed-output",
        action="store_true",
        help="Show the full PaddleX/PaddleOCR stream in addition to compact epoch progress.",
    )
    train_parser.set_defaults(func=train)

    eval_parser = sub.add_parser("evaluate", parents=[common])
    eval_parser.add_argument("--device", default="gpu:0")
    eval_parser.add_argument("--weight", required=True)
    eval_parser.set_defaults(func=evaluate)

    export_parser = sub.add_parser("export")
    export_parser.add_argument("--model", default="PP-OCRv6_medium_rec", choices=sorted(PRETRAIN_URLS))
    export_parser.add_argument("--device", default="gpu:0")
    export_parser.add_argument("--weight", required=True)
    export_parser.add_argument("--output", required=True)
    export_parser.set_defaults(func=export)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
