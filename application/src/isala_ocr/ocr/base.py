from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

import numpy as np

from ..models import OCRToken


def apply_character_whitelist(text: str, whitelist: str | None) -> str:
    """Strip characters not in ``whitelist`` from recognized text, in order.

    Engines that constrain recognition at decode time (``tesseract.py``, via
    ``-c tessedit_char_whitelist=...``) never produce a disallowed character
    in the first place. PaddleOCR (the production engine) has no equivalent
    runtime API -- its character set comes from the trained model, not a
    per-call parameter -- so ``FieldSpec.whitelist`` used to be a silent
    no-op there (CODE_REVIEW_v3.16.0.md, sectie Middel). This applies the
    whitelist post-hoc instead: any recognized character outside it is
    dropped from the text. This is not equivalent to constrained decoding --
    the remaining text can differ from what a whitelist-aware decoder would
    have produced (e.g. a stray recognized 'O' in "12O.5" becomes "12.5", not
    the "125" a real digit-only decoder might have guessed) -- but it is
    closer to the configured intent than ignoring the whitelist outright.
    """
    if not whitelist:
        return text
    allowed = set(whitelist)
    return "".join(character for character in text if character in allowed)


class OCREngine(ABC):

    def warmup(self) -> None:
        """Initialize expensive runtime state before a batch starts."""
        return None
    @abstractmethod
    def recognize_many(
        self,
        images: Sequence[np.ndarray],
        whitelists: Sequence[str | None] | None = None,
    ) -> list[list[OCRToken]]:
        raise NotImplementedError

    @abstractmethod
    def info(self) -> dict[str, object]:
        raise NotImplementedError
