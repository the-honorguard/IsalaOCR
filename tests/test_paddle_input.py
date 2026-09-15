import numpy as np
import pytest

from isala_ocr.ocr.paddle import PaddleEngine


class RecordingPipeline:
    def __init__(self):
        self.images = None

    def predict(self, images):
        self.images = list(images)
        return [
            {"rec_texts": [], "rec_scores": [], "rec_boxes": []}
            for _ in self.images
        ]


def test_grayscale_images_are_converted_before_paddle_prediction():
    pipeline = RecordingPipeline()
    engine = PaddleEngine({})
    engine._pipeline = pipeline

    result = engine.recognize_many([np.zeros((12, 24), dtype=np.uint8)])

    assert result == [[]]
    assert pipeline.images is not None
    assert pipeline.images[0].shape == (12, 24, 3)
    assert pipeline.images[0].dtype == np.uint8
    assert pipeline.images[0].flags.c_contiguous


def test_single_channel_and_alpha_images_become_three_channel_uint8():
    single = np.ones((5, 7, 1), dtype=np.float32) * 12.5
    alpha = np.zeros((5, 7, 4), dtype=np.uint8)

    prepared_single = PaddleEngine._prepare_image(single)
    prepared_alpha = PaddleEngine._prepare_image(alpha)

    assert prepared_single.shape == (5, 7, 3)
    assert prepared_single.dtype == np.uint8
    assert np.all(prepared_single == 12)
    assert prepared_alpha.shape == (5, 7, 3)


def test_invalid_image_shape_is_rejected():
    with pytest.raises(ValueError, match="Unsupported OCR image shape"):
        PaddleEngine._prepare_image(np.zeros((2, 3, 4, 5), dtype=np.uint8))


class ScriptedPipeline:
    """Returns fixed rec_texts/rec_scores/rec_boxes regardless of input images."""

    def __init__(self, results):
        self._results = results

    def predict(self, images):
        return self._results


def test_whitelist_strips_disallowed_characters_from_recognized_text():
    # PaddleOCR has no runtime API to constrain its trained character
    # dictionary (CODE_REVIEW_v3.16.0.md, sectie Middel: "FieldSpec.whitelist
    # is een no-op in productie"), so the whitelist is applied post-hoc.
    engine = PaddleEngine({})
    engine._pipeline = ScriptedPipeline([
        {"rec_texts": ["12O.5"], "rec_scores": [0.9], "rec_boxes": [[0, 0, 10, 10]]},
    ])

    result = engine.recognize_many(
        [np.zeros((12, 24), dtype=np.uint8)],
        ["0123456789.,"],
    )

    assert [token.text for token in result[0]] == ["12.5"]


def test_no_whitelist_leaves_recognized_text_unchanged():
    engine = PaddleEngine({})
    engine._pipeline = ScriptedPipeline([
        {"rec_texts": ["12O.5"], "rec_scores": [0.9], "rec_boxes": [[0, 0, 10, 10]]},
    ])

    result = engine.recognize_many([np.zeros((12, 24), dtype=np.uint8)])

    assert [token.text for token in result[0]] == ["12O.5"]


def test_whitelists_length_must_match_images():
    engine = PaddleEngine({})
    engine._pipeline = ScriptedPipeline([
        {"rec_texts": [], "rec_scores": [], "rec_boxes": []},
    ])

    with pytest.raises(ValueError, match="whitelists must have the same length"):
        engine.recognize_many([np.zeros((12, 24), dtype=np.uint8)], [])
