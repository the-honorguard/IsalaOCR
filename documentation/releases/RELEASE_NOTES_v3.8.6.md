# IsalaOCR 3.8.6 — GPU PaddleDetection BuildKit fix

## Root cause

Action 17 could still fail after PaddleDetection itself had been downloaded, built and installed. PaddleX 3.7.2 calls `install_external_deps()` at the end of the repository install. That function imports GPU PaddlePaddle before checking whether PaddleDetection's optional rotated-object-detection CUDA extension should be compiled.

During a normal Docker/BuildKit image build, the host NVIDIA driver library `libcuda.so.1` is intentionally not injected into the build container. The import therefore failed with `ImportError: libcuda.so.1: cannot open shared object file`.

## Fix

- Keep the normal `paddlex --install PaddleDetection` workflow, dependency resolver, `sklearn` replacement, `paddledet` wheel installation and PaddleX `.installed` marker.
- Patch the checksum-pinned PaddleX source with a build-only `PADDLE_PDX_SKIP_EXTERNAL_DEPS=1` guard before its unconditional `import paddle`.
- Skip only PaddleDetection's optional external-deps hook during image build. For PaddleDetection this hook exists to compile the rotated-object-detection custom operator; PicoDet-S does not need that operator.
- After the image is built, action 17 starts `trainer-gpu-detection` with `gpus: all` and validates PaddlePaddle, CUDA visibility and `ppdet` import at runtime.
- Keep `TRAINING_IMAGE_VERSION` at 3.8.4 so existing CPU and GPU-recognition images remain reusable. The failed detector image is rebuilt from the corrected Dockerfile when action 17 runs.
