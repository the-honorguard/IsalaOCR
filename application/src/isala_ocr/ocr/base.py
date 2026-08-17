from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

import numpy as np

from ..models import OCRToken


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
