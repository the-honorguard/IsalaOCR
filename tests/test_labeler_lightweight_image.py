from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_compose_uses_dedicated_labeler_dockerfile() -> None:
    compose = read("infrastructure/docker/compose.yaml")
    assert "dockerfile: infrastructure/docker/Dockerfile.labeler" in compose
    assert "image: isalaocr-labeler:3.14.0" in compose
    assert 'command: ["--workspace", "/training/workspace"' in compose


def test_labeler_image_excludes_ocr_and_dicom_dependencies() -> None:
    dockerfile = read("infrastructure/docker/Dockerfile.labeler")
    lowered = dockerfile.lower()
    executable_lines = "\n".join(
        line for line in lowered.splitlines() if not line.lstrip().startswith("#")
    )
    assert "flask" in executable_lines
    assert "waitress" in executable_lines
    # No package extras or system OCR libraries may be installed in this image.
    assert '".[paddle' not in executable_lines
    assert "paddleocr" not in executable_lines
    assert "paddlepaddle" not in executable_lines
    assert "opencv-python" not in executable_lines
    assert "tesseract-ocr" not in executable_lines
    assert "pydicom" not in executable_lines


def test_labeler_entrypoint_does_not_import_main_cli() -> None:
    server = read("application/src/isala_ocr/training/labeler_server.py")
    assert "from .labeler import serve_labeler" in server
    assert "isala_ocr.cli" not in server
    assert "from ..cli" not in server


def test_labeler_dockerfile_copies_only_web_components() -> None:
    dockerfile = read("infrastructure/docker/Dockerfile.labeler")
    assert "COPY application/src/isala_ocr/training/templates" in dockerfile
    assert "COPY application/src/isala_ocr/training/header_normalization.py" in dockerfile
    assert "COPY application/src/isala_ocr/training/dynamic_locator.py" in dockerfile
    assert "COPY application/src/isala_ocr/training/generic_detection.py" in dockerfile
    assert "COPY application/src/isala_ocr/training/mapping.py" in dockerfile
    assert "COPY application/src /app/src" not in dockerfile
    assert "COPY config" not in dockerfile
    assert "COPY schemas" not in dockerfile


def test_labeler_network_is_reachable_only_on_loopback() -> None:
    compose = read("infrastructure/docker/compose.yaml")
    assert "internal: true" not in compose
    assert "name: isalaocr-label-ui-v340" in compose
    assert 'com.docker.network.bridge.host_binding_ipv4: "127.0.0.1"' in compose
    assert '127.0.0.1:${ISALA_LABEL_PORT:-8088}:8088' in compose


def test_mapping_ui_defers_heavy_image_and_ocr_imports() -> None:
    mapping = read("application/src/isala_ocr/training/mapping.py")
    top_level = mapping.split("def _unique", 1)[0]
    assert "import cv2" not in top_level
    assert "import numpy" not in top_level
    assert "from ..ocr.base import OCREngine" not in top_level.split("if TYPE_CHECKING:", 1)[0]
    assert "Heavy image dependencies are imported lazily" in mapping


def test_labeler_dockerfile_copies_project_workspace_module() -> None:
    dockerfile = read("infrastructure/docker/Dockerfile.labeler")
    assert "COPY application/src/isala_ocr/training/projects.py /app/src/isala_ocr/training/projects.py" in dockerfile


def test_labeler_web_local_imports_are_present_in_lightweight_image() -> None:
    """Prevent runtime-only ModuleNotFoundError regressions in the labeler image.

    Dockerfile.labeler intentionally copies a small Python subset instead of the
    complete application package. Every relative Python dependency of every
    copied module must therefore also be copied explicitly.
    """
    import ast
    import re

    dockerfile = read("infrastructure/docker/Dockerfile.labeler")
    copied: set[str] = set()
    pattern = re.compile(
        r"^COPY application/src/isala_ocr/(?P<src>[^ ]+\.py) /app/src/isala_ocr/[^ ]+\.py$",
        re.MULTILINE,
    )
    for match in pattern.finditer(dockerfile):
        copied.add(match.group("src").replace("/", ".")[:-3])

    missing: set[str] = set()
    for module in sorted(copied):
        if module == "__init__":
            path = ROOT / "application" / "src" / "isala_ocr" / "__init__.py"
            package_parts: list[str] = []
        else:
            path = ROOT / "application" / "src" / "isala_ocr" / (module.replace(".", "/") + ".py")
            package_parts = module.rsplit(".", 1)[0].split(".") if "." in module else []
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # Startup failures come from module-level imports. Imports inside
        # functions or TYPE_CHECKING blocks are deliberately lazy and do not
        # belong in this lightweight image dependency closure.
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom) or node.level <= 0:
                continue
            base = package_parts[: len(package_parts) - (node.level - 1)]
            if node.module:
                base.extend(node.module.split("."))
            imported = ".".join(base)
            if imported and imported not in copied:
                missing.add(imported)

    assert not missing, f"Labeler Dockerfile misses local module(s): {sorted(missing)}"


def test_detection_gate_dependency_is_lightweight_and_copied_into_labeler() -> None:
    dockerfile = read("infrastructure/docker/Dockerfile.labeler")
    dataset_module = read("application/src/isala_ocr/training/localization_dataset.py")
    gate_module = read("application/src/isala_ocr/training/detection_gate.py")

    assert (
        "COPY application/src/isala_ocr/training/detection_gate.py "
        "/app/src/isala_ocr/training/detection_gate.py"
    ) in dockerfile
    assert "COPY application/src/isala_ocr/training/localization.py" not in dockerfile
    assert "from .detection_gate import" in dataset_module
    assert "passes_detection_gate" in dataset_module
    assert "intersection_over_union" in dataset_module
    assert "greedy_detection_metrics" in dataset_module
    assert "import cv2" not in gate_module
    assert "import numpy" not in gate_module
    assert "isala_ocr.ocr" not in gate_module


def test_derived_detection_gate_does_not_import_heavy_localization_module() -> None:
    import ast

    path = ROOT / "application/src/isala_ocr/training/localization_dataset.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "derived_detection_gate_state"
    )
    imports = [
        node for node in ast.walk(function)
        if isinstance(node, ast.ImportFrom)
    ]
    assert any(node.module == "detection_gate" for node in imports)
    assert not any(node.module == "localization" for node in imports)


def test_visual_diagnostics_do_not_lazy_import_heavy_localization_module() -> None:
    import ast

    path = ROOT / "application/src/isala_ocr/training/localization_dataset.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for function_name in ("_evaluate_prediction_map", "_detection_match_details"):
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        )
        imports = [node for node in ast.walk(function) if isinstance(node, ast.ImportFrom)]
        assert any(node.module == "detection_gate" for node in imports)
        assert not any(node.module == "localization" for node in imports)
