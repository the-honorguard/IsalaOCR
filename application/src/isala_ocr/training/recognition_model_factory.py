from __future__ import annotations

from typing import Any


RECOGNITION_STEP_KEYS = (
    "recognition-scope",
    "recognition-gt-studio",
    "recognition-dataset",
    "recognition-train",
    "recognition-evaluate",
    "recognition-models",
    "recognition-output-review",
)
APPLICATION_STEP_KEYS = (
    "mapping",
    "apply-mapping",
    "value-extract",
    "value-review",
)


def install_recognition_model_factory_metadata(webui_module: Any) -> None:
    """Repair the workflow boundary without deleting legacy routes/jobs.

    `webui.py` still contains older numeric/group metadata for backwards
    compatibility. This installer makes recognition model training part of the
    Model Factory at runtime and leaves Mapping as optional application logic.
    """
    actions = webui_module.ACTIONS
    actions["23"] = "Recognition Ground Truth uit canonieke cellen voorbereiden"
    webui_module.ACTION_DURATION_ESTIMATES["23"] = {
        "label": "± 1–10 min",
        "detail": "Maakt neutrale cell-crops en een baseline OCR-voorzet; afhankelijk van het aantal canonieke GT-cellen.",
    }

    steps = webui_module.PROCESS_STEPS
    by_key = {str(item.get("key") or ""): item for item in steps}

    inserts = [{
        "key": "recognition-scope",
        "index": 8,
        "group": "value",
        "title": "Recognition-scope",
        "subtitle": "Kies per project welke panelen en kolommen Recognition-samples leveren.",
        "action_ids": [],
        "requirements": ["Canonieke table-cell Ground Truth"],
    }, {
        "key": "recognition-gt-studio",
        "index": 9,
        "group": "value",
        "title": "Recognition GT Studio",
        "subtitle": "Maak, bekijk en corrigeer neutrale crop→tekst samples rechtstreeks uit de geselecteerde panelen en kolommen.",
        "action_ids": ["23"],
        "requirements": ["Canonieke table-cell Ground Truth", "Recognition-scope", "Bronrenders", "Pretrained/generieke recognition-runtime"],
    }]
    insertion_index = next(
        (index for index, item in enumerate(steps) if str(item.get("key") or "") == "mapping"),
        len(steps),
    )
    for offset, item in enumerate(inserts):
        if item["key"] not in by_key:
            steps.insert(insertion_index + offset, item)
            by_key[item["key"]] = item

    recognition_updates = {
        "recognition-dataset": (10, "Recognition Model Factory", "Bouw, train, beoordeel en activeer het Recognition-model vanuit één pagina."),
        "recognition-train": (None, "Recognition-model trainen · legacy", "Legacy-route; gebruik de gecombineerde Recognition Model Factory."),
        "recognition-evaluate": (None, "Recognition-model beoordelen · legacy", "Legacy-route; gebruik de gecombineerde Recognition Model Factory."),
        "recognition-models": (None, "Recognition-model activeren · legacy", "Legacy-route; gebruik de gecombineerde Recognition Model Factory."),
    }
    for key, (index, title, subtitle) in recognition_updates.items():
        step = by_key.get(key)
        if step is None:
            continue
        step.update(index=index, title=title, subtitle=subtitle)

    application_updates = {
        "mapping": ("Mapping Studio", "Koppel gelezen tabellabels aan applicatievelden."),
        "apply-mapping": ("Mappings toepassen", "Materialiseer functionele ROI/output-koppelingen uit bevestigde mappings."),
        "value-extract": ("Application output uitlezen", "Draai het getrainde recognitionmodel op de functioneel geselecteerde ROI's."),
        "value-review": ("Application output beoordelen", "Beoordeel de uiteindelijke functionele output; hier kan bijvoorbeeld '-' als missing/null worden geïnterpreteerd."),
    }
    for key, (title, subtitle) in application_updates.items():
        step = by_key.get(key)
        if step is None:
            continue
        step.update(index=None, title=title, subtitle=subtitle)

    # Rebuild the lookup because two steps were inserted after webui.py created it.
    webui_module.PROCESS_STEP_BY_KEY.clear()
    webui_module.PROCESS_STEP_BY_KEY.update({str(item["key"]): item for item in steps})
