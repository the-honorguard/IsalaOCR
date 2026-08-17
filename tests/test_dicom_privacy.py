from pathlib import Path

import numpy as np
import pytest

pydicom = pytest.importorskip("pydicom")

from isala_ocr.dicom import decode_dicom


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
