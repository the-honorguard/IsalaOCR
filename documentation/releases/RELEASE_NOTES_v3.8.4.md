# IsalaOCR v3.8.4 — GPU PaddleDetection installation hotfix

## Root cause

The GPU training image failed at `paddlex --install PaddleDetection`. The preceding DejaVuSans warning and the message that PicoDet-S model files already exist are informational and are not the failing step.

PaddleDetection's current requirements contain both `scikit-learn` and the obsolete compatibility package `sklearn==0.0`. PyPI has intentionally rejected installation of the deprecated `sklearn` package since 1 December 2023. PaddleX 3.7.x already supports dependency replacement during plugin installation, so v3.8.4 omits only `PaddleDetection.sklearn` and retains the real `scikit-learn` dependency.

The detector plugin is installed with:

```text
paddlex --install PaddleDetection --deps_to_replace PaddleDetection.sklearn=None
```

The build continues to avoid importing PaddlePaddle while a GPU image is being built, because `libcuda.so.1` is injected only when the image is started through the NVIDIA container runtime.

## Independent preparation components

Action 1 remains the backwards-compatible "prepare everything" path. The same work can now be executed independently:

- Action 14: inference OCR/table models.
- Action 15: CPU detector/PicoDet-S stack and official PicoDet-S baseline.
- Action 16: GPU OCR-recognition stack. This image does **not** install PaddleDetection.
- Action 17: dedicated GPU PaddleDetection/PicoDet-S stack.
- Action 18: PP-OCRv6 pretrained recognition training weight.

GPU field-detector training now uses `isalaocr-training-gpu-detection:3.8.4` through `trainer-gpu-detection`. Recognition training continues to use `isalaocr-training-gpu:3.8.4` and is no longer coupled to PaddleDetection installation.

## PaddlePaddle version

v3.8.4 deliberately keeps the v3.8.3 PaddlePaddle 3.2.2 pins. The earlier CPU PicoDet/oneDNN regression and upstream PaddleDetection compatibility reports make a blind move to 3.3.x unsafe. This release fixes the deterministic plugin-installation blocker without changing the runtime version at the same time.

## Upgrade

Extract v3.8.4 over v3.8.3. To prepare only the GPU detector, run action 17. To prepare only GPU OCR recognition, run action 16. Action 1 still prepares all components in sequence and benefits from the existing BuildKit caches.
