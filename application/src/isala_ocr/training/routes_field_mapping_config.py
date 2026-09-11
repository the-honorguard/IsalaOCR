"""Field-schema and mapping-profile management routes, split out of
webui.create_web_app.

Same pattern as the other ``routes_*`` modules split out of ``webui.py``:
the handlers move here, taking only the active project ``database``
proxy as shared state. ``apply_mapping_profile`` is a pure function
imported directly rather than passed in.
"""

from __future__ import annotations

import re

from flask import Flask, abort, flash, redirect, render_template, request, url_for

from .mapping import apply_mapping_profile


def register_field_mapping_config_routes(app: Flask, *, database) -> None:
    @app.route("/field-schema", methods=["GET", "POST"])
    def field_schema():
        if request.method == "POST":
            action = str(request.form.get("schema_action") or "save").strip().lower()
            field_key = str(request.form.get("field_key") or "").strip()
            if action == "toggle":
                database.set_field_active(field_key, str(request.form.get("active") or "0") == "1")
                flash("Veldstatus aangepast.", "success")
            elif action == "save":
                aliases_text = str(request.form.get("aliases") or "")
                aliases = [item.strip() for item in re.split(r"[,;\n]+", aliases_text) if item.strip()]

                def optional_float(name: str) -> float | None:
                    value = str(request.form.get(name) or "").strip().replace(",", ".")
                    return float(value) if value else None

                try:
                    database.upsert_field_definition(
                        field_key,
                        str(request.form.get("display_name") or ""),
                        group_name=str(request.form.get("group_name") or ""),
                        data_type=str(request.form.get("data_type") or "text"),
                        preferred_unit=str(request.form.get("preferred_unit") or ""),
                        aliases=aliases,
                        minimum_value=optional_float("minimum_value"),
                        maximum_value=optional_float("maximum_value"),
                        required=str(request.form.get("required") or "") == "1",
                        active=True,
                    )
                    flash(f"Veld {field_key} opgeslagen.", "success")
                except ValueError as exc:
                    flash(str(exc), "error")
            else:
                abort(400)
            return redirect(url_for("field_schema"))
        return render_template(
            "field_schema.html",
            fields=database.list_field_definitions(),
            data_types=["text", "decimal", "integer", "boolean", "date", "code"],
            header_counts={"total": len(database.list_field_definitions()), "pending": sum(not bool(item.get("active")) for item in database.list_field_definitions()), "accepted": sum(bool(item.get("active")) for item in database.list_field_definitions())},
            header_total_label="velden", header_pending_label="inactief", header_accepted_label="actief",
        )

    @app.route("/mapping-profiles", methods=["GET", "POST"])
    def mapping_profiles_page():
        sources = database.list_detection_sources()
        if request.method == "POST":
            action = str(request.form.get("profile_action") or "save").strip().lower()
            if action == "save":
                source_id = str(request.form.get("source_id") or "").strip()
                profile_id = str(request.form.get("profile_id") or "").strip()
                name = str(request.form.get("name") or profile_id).strip()
                try:
                    profile = database.save_mapping_profile(
                        profile_id=profile_id,
                        name=name,
                        source_id=source_id,
                        description=str(request.form.get("description") or ""),
                    )
                    flash(f"Mappingprofiel {profile['name']} opgeslagen met {len(profile.get('rules', []))} regels.", "success")
                except (ValueError, KeyError) as exc:
                    flash(str(exc), "error")
            elif action == "apply":
                source_id = str(request.form.get("source_id") or "").strip()
                profile_id = str(request.form.get("profile_id") or "").strip()
                try:
                    suggestions = apply_mapping_profile(database, profile_id, source_id)
                    flash(f"{len(suggestions)} mappings voorgesteld vanuit profiel {profile_id}.", "success")
                    return redirect(url_for("mapping_studio", source_id=source_id))
                except (ValueError, KeyError) as exc:
                    flash(str(exc), "error")
            else:
                abort(400)
            return redirect(url_for("mapping_profiles_page"))
        return render_template(
            "mapping_profiles.html",
            profiles=database.list_mapping_profiles(),
            sources=sources,
            header_counts={"total": len(database.list_mapping_profiles()), "pending": 0, "accepted": len(database.list_mapping_profiles())},
            header_total_label="profielen", header_pending_label="open", header_accepted_label="actief",
        )
