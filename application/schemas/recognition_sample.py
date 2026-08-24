"""Recognition GT Studio data contract."""

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass
class RecognitionSample:
    id: str
    detection_crop_id: str
    model_prediction: Optional[str]
    ground_truth_text: Optional[str]
    confidence: Optional[float]
    status: str
    training_enabled: bool
    correction_reason: Optional[str]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "RecognitionSample":
        """Translate the shared sample row into the Recognition GT contract."""
        return cls(
            id=str(row.get("sample_id") or row.get("id") or ""),
            detection_crop_id=str(row.get("detection_crop_id") or row.get("sample_id") or ""),
            model_prediction=row.get("model_prediction", row.get("raw_ocr")),
            ground_truth_text=row.get("ground_truth_text", row.get("exact_label")),
            confidence=row.get("confidence", row.get("raw_confidence")),
            status=str(row.get("status") or "new"),
            training_enabled=bool(row.get("training_enabled", row.get("status") in {"accepted", "training_ready"})),
            correction_reason=row.get("correction_reason", row.get("notes")),
        )


# Status values:
# new
# reviewed
# approved
# training_ready
# excluded
