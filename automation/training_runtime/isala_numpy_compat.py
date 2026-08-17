"""Compatibility aliases for NumPy 2-created pickle payloads on NumPy 1.x.

Official PaddleOCR ``.pdparams`` files can contain pickle references to
``numpy._core.multiarray`` when they were published from a NumPy 2 runtime.
NumPy 1.x exposes the equivalent implementation below ``numpy.core``.  This
module installs narrowly scoped module aliases so PaddlePaddle can load those
weights without changing the numerical stack in the reusable training image.
"""

from __future__ import annotations

import importlib
import sys


_NUMPY_CORE_SUBMODULES = (
    "multiarray",
    "_multiarray_umath",
    "numeric",
    "umath",
)


def install_numpy_pickle_compatibility() -> bool:
    """Expose NumPy 1.x core modules through their NumPy 2 pickle names.

    Returns ``True`` when aliases were installed and ``False`` when the native
    ``numpy._core`` package already exists.  Unexpected NumPy import failures
    are not hidden.
    """

    try:
        importlib.import_module("numpy._core")
        return False
    except ModuleNotFoundError as exc:
        if exc.name not in {"numpy._core", "numpy"}:
            raise

    numpy_module = importlib.import_module("numpy")
    legacy_core = importlib.import_module("numpy.core")

    sys.modules.setdefault("numpy._core", legacy_core)
    if not hasattr(numpy_module, "_core"):
        setattr(numpy_module, "_core", legacy_core)

    for name in _NUMPY_CORE_SUBMODULES:
        try:
            legacy_module = importlib.import_module(f"numpy.core.{name}")
        except ModuleNotFoundError:
            continue
        sys.modules.setdefault(f"numpy._core.{name}", legacy_module)

    return True
