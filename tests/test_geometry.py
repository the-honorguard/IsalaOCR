from isala_ocr.geometry import scale_box
from isala_ocr.models import Box


def test_scale_box_scales_and_clamps():
    result = scale_box(Box(10, 20, 60, 70), 100, 100, 200, 50)
    assert result == Box(20, 10, 120, 35)


def test_box_padding_and_clamping():
    assert Box(2, 3, 10, 11).padded(5).clamp(12, 12) == Box(0, 0, 12, 12)
