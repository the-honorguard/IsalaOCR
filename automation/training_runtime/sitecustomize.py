"""Install IsalaOCR's NumPy pickle compatibility aliases at Python startup."""

from __future__ import annotations

try:
    from isala_numpy_compat import install_numpy_pickle_compatibility

    install_numpy_pickle_compatibility()
except Exception:
    # The training runner performs a strict, user-visible verification before
    # loading weights.  Avoid turning unrelated Python commands into startup
    # failures; the targeted verifier will provide the actionable diagnostic.
    pass
