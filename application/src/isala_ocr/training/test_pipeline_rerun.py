"""Rerun an already-used training-pipeline image through the proefpagina.

``detection_sources`` (see ``db_generic_detection.py``) never stores the
original DICOM's path -- only its rendered PNG (``source_renders/<id>.png``)
and geometry. The original file itself is only findable by rescanning the
active project's input directory, since nothing deletes or moves it after
processing (``input_selection.py`` only filters *which* files a run
selects, it never relocates them).

A straight copy would not do: ``source_id`` is the sha256 of the file's
bytes (see ``image_io.hash_file`` / ``input_selection.input_file_source_id``),
so reprocessing byte-identical content through the proefpagina would land on
the *same* source_id as the original training run, silently overwriting its
output and, worse, getting marked as a proefpagina source -- which excludes
it from training review (``test_pipeline_sources.py``). ``duplicate_dicom_with_fresh_identity``
sidesteps that by giving the copy a fresh ``SOPInstanceUID`` before writing
it out: the pixel data and study metadata that the pipeline actually reads
are untouched, but the file's bytes -- and therefore its source_id -- differ
from the original.
"""

from __future__ import annotations

from pathlib import Path

from .input_selection import input_file_source_id, input_files


def find_input_file_by_source_id(input_root: Path, source_id: str) -> Path | None:
    """Return the input file whose content hash is ``source_id``, if present."""
    source_id = str(source_id or "").strip()
    if not source_id:
        return None
    for candidate in input_files(input_root):
        if input_file_source_id(candidate) == source_id:
            return candidate
    return None


def duplicate_dicom_with_fresh_identity(source_path: Path, destination_path: Path) -> None:
    """Write a copy of ``source_path`` to ``destination_path`` with a new SOPInstanceUID.

    Raises ``RuntimeError`` if pydicom is unavailable and ``ValueError`` if
    ``source_path`` cannot be read as a DICOM file -- both are caller-facing,
    user-readable failure reasons for the "Opnieuw testen" action.
    """
    try:
        import pydicom
        from pydicom.uid import generate_uid
    except ImportError as exc:
        raise RuntimeError("pydicom is vereist om een proefpagina-rerun te maken") from exc

    try:
        dataset = pydicom.dcmread(str(source_path), force=False)
    except Exception as exc:
        raise ValueError(f"Kon origineel DICOM-bestand niet lezen: {exc}") from exc

    new_uid = generate_uid()
    dataset.SOPInstanceUID = new_uid
    if getattr(dataset, "file_meta", None) is not None:
        dataset.file_meta.MediaStorageSOPInstanceUID = new_uid
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    dataset.save_as(str(destination_path))
