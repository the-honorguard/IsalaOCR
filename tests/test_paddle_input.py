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
