$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-Docker
New-Item -ItemType Directory -Force -Path input, output, models | Out-Null
& docker compose run --rm --build ocr
if ($LASTEXITCODE -ne 0) { throw "OCR execution failed." }
