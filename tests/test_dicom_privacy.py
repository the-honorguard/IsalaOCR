from pathlib import Path

import numpy as np
import pytest

pydicom = pytest.importorskip("pydicom")

from isala_ocr.dicom import _ybr_rct_to_rgb, decode_dicom


ROOT = Path(__file__).resolve().parents[1]


def test_gitignore_blocks_medical_sources_and_patient_derived_outputs() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8-sig")

    for pattern in (
        "*.dcm",
        "*.dicom",
        "*.ima",
        "*.nii",
        "*.nii.gz",
        "*.nrrd",
        "*.mha",
        "*.mhd",
        "source_renders/",
        "detected_blocks/",
        "header_crops/",
        "mapped_crops/",
        "localization_datasets/",
        "table_cell_datasets/",
    ):
        assert pattern in gitignore


def test_ybr_rct_inverse_is_reversible_for_known_rgb_values() -> None:
    rgb = np.array([[[10, 20, 30], [240, 120, 40]]], dtype=np.int64)
    y = np.floor_divide(rgb[..., 0] + 2 * rgb[..., 1] + rgb[..., 2], 4)
    cb = rgb[..., 2] - rgb[..., 1]
    cr = rgb[..., 0] - rgb[..., 1]
    ybr_rct = np.stack((y, cb, cr), axis=-1)
    np.testing.assert_array_equal(_ybr_rct_to_rgb(ybr_rct), rgb)


def test_dicom_decoder_does_not_expose_patient_identifiers(tmp_path: Path):
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(str(tmp_path / "test.dcm"), {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = SecondaryCaptureImageStorage
    dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    dataset.PatientName = "Sensitive^Person"
    dataset.PatientID = "123456789"
    dataset.Modality = "OT"
    dataset.Rows = 8
    dataset.Columns = 8
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 8
    dataset.BitsStored = 8
    dataset.HighBit = 7
    dataset.PixelRepresentation = 0
    dataset.PixelData = np.arange(64, dtype=np.uint8).reshape(8, 8).tobytes()
    path = tmp_path / "test.dcm"
    dataset.save_as(path)

    decoded = decode_dicom(path)
    serialized = str(decoded.safe_metadata)
    assert "Sensitive" not in serialized
    assert "123456789" not in serialized
    assert decoded.image.shape == (8, 8, 3)
