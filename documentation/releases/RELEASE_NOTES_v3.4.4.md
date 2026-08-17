# IsalaOCR v3.4.4

## GPU preflight stability

The Windows PowerShell 5.1 preflight no longer launches a separate GPU-enabled
Compose container. Docker Desktop can return an incomplete process object for
that specific `Start-Process` invocation, which caused the checker itself to
abort with `You cannot call a method on a null-valued expression.`

The preflight still verifies the dataset, dictionary, pretrained weights,
Docker Engine, Compose configuration, bind-mount permissions and presence of
the reusable GPU image. CUDA and visible-device verification is performed by
the actual `trainer-gpu` container immediately before training begins. Training
still fails before epoch 1 when PaddlePaddle has no usable CUDA device.

The reusable training image revision remains 3.3.11; no large image rebuild is
required for this host-script-only update.
