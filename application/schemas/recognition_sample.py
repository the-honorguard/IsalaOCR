"""Recognition GT Studio data contract."""

from dataclasses import dataclass
from typing import Optional


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


# Status values:
# new
# reviewed
# approved
# training_ready
# excluded
