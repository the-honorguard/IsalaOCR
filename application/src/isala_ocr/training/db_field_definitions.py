"""``TrainingDatabase`` field-definition (editable field schema) methods.

Split out of ``db.py`` (see ``documentation/architecture/db-webui-split-plan.md``)
as a mixin, following the same pattern as ``db_samples.py``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .db_constants import VALID_FIELD_TYPES, utc_now
from .generic_detection import normalize_text


class FieldDefinitionsMixin:
    def fields(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT field_key, field_label, COUNT(*) AS count,
                       SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) AS accepted
                FROM samples WHERE roi_review_status='correct'
                GROUP BY field_key, field_label ORDER BY field_key
                """
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _safe_field_key(value: str) -> str:
        key = re.sub(r"[^a-z0-9_.-]+", "_", str(value or "").strip().casefold()).strip("_.-")
        if not key:
            raise ValueError("Field key cannot be empty")
        if len(key) > 160:
            raise ValueError("Field key is too long")
        return key

    def seed_field_definitions(self, definitions: list[dict[str, Any]]) -> int:
        """Insert built-in field definitions without overwriting user edits."""
        now = utc_now()
        inserted = 0
        with self.connect() as db:
            for item in definitions:
                key = self._safe_field_key(str(item.get("field_key") or item.get("key") or ""))
                aliases = [str(value).strip() for value in item.get("aliases", []) if str(value).strip()]
                data_type = str(item.get("data_type") or "text").strip().lower()
                if data_type not in VALID_FIELD_TYPES:
                    data_type = "text"
                result = db.execute(
                    """
                    INSERT OR IGNORE INTO field_definitions(
                        field_key, display_name, group_name, data_type, preferred_unit,
                        aliases_json, minimum_value, maximum_value, required, active,
                        built_in, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        key,
                        str(item.get("display_name") or item.get("label") or key),
                        str(item.get("group_name") or item.get("group") or ""),
                        data_type,
                        str(item.get("preferred_unit") or item.get("unit") or ""),
                        json.dumps(aliases, ensure_ascii=False),
                        item.get("minimum_value"),
                        item.get("maximum_value"),
                        1 if item.get("required") else 0,
                        1,
                        1 if item.get("built_in", True) else 0,
                        now,
                        now,
                    ),
                )
                inserted += int(result.rowcount > 0)
            self._strip_leaked_builtin_aliases(db, definitions, now)
        return inserted

    @staticmethod
    def _strip_leaked_builtin_aliases(db: Any, definitions: list[dict[str, Any]], now: str) -> None:
        """Repair learned aliases that leaked between neighbouring built-in fields.

        Confirming a mapping learns the observed label as an alias of its
        field. Older versions did this without checking other fields, so e.g.
        "ED Volume" and "ES Volume" ended up in ``lv_cardiac_density``'s and
        ``lv_ed_volume``'s alias lists. Those fields then all scored an exact
        alias on the same row and the suggestion shifted every value one row
        (ED Volume's number landing in Cardiac Density, and so on).

        An alias is removed from a field when it is a built-in alias of a
        *different* field and not one of its own. Left/Right ventricle fields
        legitimately share labels, which is covered by each keeping its own
        aliases; aliases leaked across groups (e.g. "Heart rate" in a
        ventricle field) are removed as well.

        Aliases are compared with ``normalize_text`` -- the same normalisation
        ``schema_candidate_score`` uses for exact-alias matches -- so
        punctuation/accent variants of a leaked alias are caught as well.
        """
        norm = normalize_text

        own: dict[str, set[str]] = {}
        for item in definitions:
            key = FieldDefinitionsMixin._safe_field_key(str(item.get("field_key") or item.get("key") or ""))
            own[key] = {norm(value) for value in item.get("aliases", []) if norm(value)}
        for key, aliases_own in own.items():
            foreign = {
                alias
                for other, other_aliases in own.items()
                if other != key
                for alias in other_aliases
            } - aliases_own
            if not foreign:
                continue
            row = db.execute("SELECT aliases_json FROM field_definitions WHERE field_key=?", (key,)).fetchone()
            if row is None:
                continue
            try:
                aliases = json.loads(row["aliases_json"] or "[]")
            except (TypeError, ValueError):
                continue
            if not isinstance(aliases, list):
                continue
            kept = [alias for alias in aliases if norm(alias) not in foreign]
            if len(kept) != len(aliases):
                db.execute(
                    "UPDATE field_definitions SET aliases_json=?, updated_at=? WHERE field_key=?",
                    (json.dumps(kept, ensure_ascii=False), now, key),
                )

    def upsert_field_definition(
        self,
        field_key: str,
        display_name: str,
        *,
        group_name: str = "",
        data_type: str = "text",
        preferred_unit: str = "",
        aliases: list[str] | None = None,
        minimum_value: float | None = None,
        maximum_value: float | None = None,
        required: bool = False,
        active: bool = True,
        built_in: bool = False,
    ) -> dict[str, Any]:
        key = self._safe_field_key(field_key)
        name = str(display_name or "").strip()
        if not name:
            raise ValueError("Display name cannot be empty")
        data_type = str(data_type or "text").strip().lower()
        if data_type not in VALID_FIELD_TYPES:
            raise ValueError(f"Unsupported field type: {data_type}")
        aliases = [str(value).strip() for value in (aliases or []) if str(value).strip()]
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO field_definitions(
                    field_key, display_name, group_name, data_type, preferred_unit,
                    aliases_json, minimum_value, maximum_value, required, active,
                    built_in, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(field_key) DO UPDATE SET
                    display_name=excluded.display_name,
                    group_name=excluded.group_name,
                    data_type=excluded.data_type,
                    preferred_unit=excluded.preferred_unit,
                    aliases_json=excluded.aliases_json,
                    minimum_value=excluded.minimum_value,
                    maximum_value=excluded.maximum_value,
                    required=excluded.required,
                    active=excluded.active,
                    built_in=CASE WHEN field_definitions.built_in=1 THEN 1 ELSE excluded.built_in END,
                    updated_at=excluded.updated_at
                """,
                (
                    key, name, str(group_name or ""), data_type, str(preferred_unit or ""),
                    json.dumps(aliases, ensure_ascii=False), minimum_value, maximum_value,
                    1 if required else 0, 1 if active else 0, 1 if built_in else 0,
                    now, now,
                ),
            )
        result = self.get_field_definition(key)
        if result is None:
            raise RuntimeError("Field definition was not stored")
        return result

    def set_field_active(self, field_key: str, active: bool) -> None:
        with self.connect() as db:
            changed = db.execute(
                "UPDATE field_definitions SET active=?, updated_at=? WHERE field_key=?",
                (1 if active else 0, utc_now(), field_key),
            ).rowcount
            if not changed:
                raise KeyError(field_key)

    def get_field_definition(self, field_key: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM field_definitions WHERE field_key=?", (field_key,)
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        try:
            item["aliases"] = json.loads(item.pop("aliases_json") or "[]")
        except (TypeError, ValueError):
            item["aliases"] = []
        return item

    def list_field_definitions(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        where = "WHERE active=1" if active_only else ""
        with self.connect() as db:
            rows = db.execute(
                f"SELECT * FROM field_definitions {where} ORDER BY group_name, display_name, field_key"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["aliases"] = json.loads(item.pop("aliases_json") or "[]")
            except (TypeError, ValueError):
                item["aliases"] = []
            result.append(item)
        return result
