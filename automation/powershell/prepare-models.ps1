$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-Docker
New-Item -ItemType Directory -Force -Path models | Out-Null
& docker compose --profile setup run --rm --build model-prep
if ($LASTEXITCODE -ne 0) { throw "Model preparation failed." }
