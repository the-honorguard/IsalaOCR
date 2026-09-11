# Recognition GT workflow

Recognition GT is separate from Detection GT.

## Detection model

Purpose: find regions, panels, cells and text locations.

Training input:
- image
- bounding boxes
- detection classes

## Recognition model

Purpose: read the content of detected crops.

Training input:
- crop generated from detection
- ground truth text/value
- optional field mapping

## Iteration loop

```
Recognition GT Studio
        ↓
Recognition dataset
        ↓
Recognition model training
        ↓
Recognition evaluation
        ↓
Recognition GT improvements
        ↺
```

Recognition GT must never replace or modify Detection GT annotations.
