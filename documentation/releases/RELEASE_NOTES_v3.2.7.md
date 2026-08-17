# IsalaOCR Local v3.2.7

This is a consolidated complete source distribution. It includes the dynamic locator and every code hotfix through v3.2.7.

## Included fixes

- automatic Docker Desktop startup and bounded engine preflight;
- SQLite schema migration ordering;
- reusable Docker dependency caches;
- host input preflight;
- writable offline PaddleX runtime cache;
- complete inference-model preparation from menu option 1;
- Path-aware PaddleX training-runtime discovery used by dataset validation and training.

## Deliberately excluded

The archive does not contain local DICOMs, output, model weights, review databases, crops, datasets, training runs or registered models. Extracting it over an existing project updates code without intentionally replacing those runtime assets.

## Existing installation

1. Stop the label interface with menu option 4.
2. Extract the archive over the active IsalaOCR project folder and replace code files.
3. Run `Get-ChildItem -Recurse -File | Unblock-File`.
4. Start `TRAINING_MENU.cmd`.
5. Continue with option 8; the existing 224 reviewed samples and latest dataset remain in the local `training` folder.
