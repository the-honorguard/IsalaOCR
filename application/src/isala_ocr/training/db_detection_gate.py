"""``TrainingDatabase`` detection-gate methods.

Split out of ``db.py`` (see ``documentation/architecture/db-webui-split-plan.md``)
as a mixin, following the same pattern as ``db_samples.py``. This is the last
of the mixin extractions in the plan; db.py now holds only the schema/
connection core plus the ``TrainingDatabase`` class composition.
"""

from __future__ import annotations

import json
from typing import Any

from .db_constants import utc_now


class DetectionGateMixin:
    def set_detection_gate(self, ready: bool, *, reason: str, evaluation_id: str = "") -> None:
        updated_at = utc_now()
        values = {
            "detection_gate_ready":"1" if ready else "0",
            "detection_gate_reason":str(reason or ""),
            "detection_gate_evaluation_id":str(evaluation_id or ""),
            "detection_gate_updated_at":updated_at,
        }
        with self.connect() as db:
            for key,value in values.items():
                db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",(key,value))
        # Host-side PowerShell actions cannot rely on a local sqlite3 executable.
        # Mirror the authoritative DB state to a small JSON gate file so direct
        # menu actions are blocked before Docker value processing starts.
        gate_file = self.path.parent / "detection_gate.json"
        temporary = gate_file.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({
            "ready": bool(ready), "reason": str(reason or ""),
            "evaluation_id": str(evaluation_id or ""), "updated_at": updated_at,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(gate_file)

    def detection_gate(self) -> dict[str, Any]:
        with self.connect() as db:
            rows=db.execute("SELECT key,value FROM metadata WHERE key LIKE 'detection_gate_%'").fetchall()
        values={str(row["key"]):str(row["value"]) for row in rows}
        return {
            "ready": values.get("detection_gate_ready") == "1",
            "reason": values.get("detection_gate_reason", "Nog geen localization-evaluatie die de kwaliteitspoort haalt."),
            "evaluation_id": values.get("detection_gate_evaluation_id", ""),
            "updated_at": values.get("detection_gate_updated_at", ""),
        }
