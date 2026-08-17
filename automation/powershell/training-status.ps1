. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId "3"
Assert-Docker
docker compose --profile training run --rm --build evaluator `
    training-status --workspace /training/workspace --config /app/config/app.yaml
