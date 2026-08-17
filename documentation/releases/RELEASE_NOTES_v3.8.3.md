# IsalaOCR v3.8.3 — PicoDet CPU / oneDNN compatibility hotfix

## Fixed

Action 1 reached the official PicoDet-S localization baseline successfully, but the CPU smoke inference failed inside PaddlePaddle 3.3.0 with:

```text
NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute not support
[pir::ArrayAttribute<pir::DoubleAttribute>]
```

This is an upstream PaddlePaddle 3.3.x CPU oneDNN/PIR regression rather than an IsalaOCR dataset or project-workspace error. The official workaround is to use the pre-regression 3.2.x runtime.

The reusable CPU and GPU training images are now pinned to PaddlePaddle 3.2.2. The training-image revision is bumped from 3.7.0 to 3.8.3, which prevents previously built images containing 3.3.0 from satisfying training preflight checks.

The localization runner also performs a defensive CPU runtime check. If a local environment override reintroduces PaddlePaddle 3.3.x, preparation/prediction stops immediately with a direct explanation instead of failing deep inside oneDNN. The localization preparation manifest records the PaddlePaddle version used for the successful smoke test.

## Upgrade

Extract v3.8.3 over v3.8.2 and run action 1 again. BuildKit can reuse the already downloaded PaddleX source, official models, base-image layers and caches; the PaddlePaddle dependency layer must be rebuilt because the training runtime version changes. Existing projects, reviews, datasets, mappings and model registries are unchanged.
