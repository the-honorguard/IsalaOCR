# IsalaOCR 3.9.6

Artifact management reliability update.

- Dataset deletion now has persistent error/success feedback.
- The current work dataset can be replaced and removed in one guarded action when another dataset exists.
- Dependency conflicts are checked before changing the work-dataset pointer.
- Cascade deletion no longer suppresses its own errors.
- Datasets linked to the active field detector remain protected.
