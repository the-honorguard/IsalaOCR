from isala_ocr.config import FieldSpec, Profile
from isala_ocr.models import Box, OCRToken
from isala_ocr.training.dynamic_locator import locate_fields, normalize_for_matching


def token(text: str, x1: int, y1: int, x2: int, y2: int, confidence: float = 0.95):
    return OCRToken(text=text, confidence=confidence, box=Box(x1, y1, x2, y2))


def profile() -> Profile:
    fields = [
        FieldSpec("lv_ed_volume", "Left ventricle ED Volume", Box(180, 80, 330, 104), "ml", None, None, 1, False, None, "lv", ("ED Volume",)),
        FieldSpec("lv_ed_volume_bsa", "Left ventricle ED Volume/BSA", Box(180, 203, 340, 228), "ml/m²", None, None, 1, False, None, "lv", ("ED Volume/BSA",)),
        FieldSpec("rv_stroke_volume", "Right ventricle Stroke Volume", Box(180, 613, 330, 638), "ml", None, None, 1, False, None, "rv", ("Stroke Volume",)),
    ]
    return Profile(
        name="dynamic-test",
        description="",
        reference_width=800,
        reference_height=800,
        anchors=[],
        fields=fields,
        consistency_rules=[],
        dynamic_extraction={
            "enabled": True,
            "panel_search_x2": 600,
            "fallback_label_column": [0, 170],
            "fallback_value_column": [180, 390],
            "header_search_x1": 130,
            "header_search_x2": 600,
            "right_panel_titles": ["Right ventricle Volume Result"],
            "value_headers": ["Endo Volume"],
            "normal_headers": ["Normal Values"],
            "label_match_threshold": 0.72,
            "row_half_height": 13,
        },
    )


def test_dynamic_locator_uses_row_labels_when_field_order_changes():
    tokens = [
        token("Endo", 210, 55, 250, 68), token("Volume", 255, 55, 310, 68),
        token("Normal", 450, 55, 500, 68), token("Values", 505, 55, 555, 68),
        token("ED", 10, 90, 28, 103), token("Volume/BSA", 32, 90, 115, 103),
        token("89.1", 220, 90, 255, 103), token("ml/m²", 260, 90, 305, 103),
        token("ED", 10, 140, 28, 153), token("Volume", 32, 140, 85, 153),
        token("156.1", 220, 140, 265, 153), token("ml", 270, 140, 290, 153),
        token("Right", 190, 410, 230, 423), token("ventricle", 235, 410, 300, 423),
        token("Volume", 305, 410, 355, 423), token("Result", 360, 410, 410, 423),
        token("Endo", 210, 455, 250, 468), token("Volume", 255, 455, 310, 468),
        token("Normal", 450, 455, 500, 468), token("Values", 505, 455, 555, 468),
        # Stroke Volume is deliberately far from the legacy fixed y=613 ROI.
        token("Stroke", 10, 520, 58, 533), token("Volume", 62, 520, 115, 533),
        token("80.7", 220, 520, 255, 533), token("ml", 260, 520, 280, 533),
    ]
    located, diagnostics = locate_fields((800, 800), tokens, profile(), padding_pixels=0)
    by_key = {item.field.key: item for item in located}

    assert diagnostics["panel_divider_y"] == 410
    assert by_key["lv_ed_volume"].method == "dynamic_token_box"
    assert by_key["lv_ed_volume"].box.y1 < 140 < by_key["lv_ed_volume"].box.y2
    assert by_key["lv_ed_volume_bsa"].box.y1 < 90 < by_key["lv_ed_volume_bsa"].box.y2
    assert by_key["rv_stroke_volume"].box.y1 < 520 < by_key["rv_stroke_volume"].box.y2
    assert by_key["rv_stroke_volume"].box.y2 < 560


def test_ed_and_es_or_bsa_labels_are_not_fuzzy_interchanged():
    assert normalize_for_matching("ED Volume/BSA") == "ed volume bsa"
    p = profile()
    only_bsa = [
        token("Endo Volume", 210, 55, 310, 68),
        token("Normal Values", 450, 55, 555, 68),
        token("ED Volume/BSA", 10, 90, 115, 103),
        token("89.1 ml/m²", 220, 90, 305, 103),
    ]
    located, _ = locate_fields((800, 800), only_bsa, p, padding_pixels=0)
    by_key = {item.field.key: item for item in located}
    assert by_key["lv_ed_volume_bsa"].method == "dynamic_token_box"
    assert by_key["lv_ed_volume"].method == "fixed_fallback"
