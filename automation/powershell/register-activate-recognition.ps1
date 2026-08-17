. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId "28"
Assert-IsalaDetectionGateOpen
$env:ISALA_NESTED_PREFLIGHT_APPROVED = "1"
try {
    & (Join-Path $PSScriptRoot "register-recognition-model.ps1")
    $registry = Join-Path (Get-IsalaHostProjectRegistry) "models"
    $latest = Get-ChildItem -LiteralPath $registry -Directory -ErrorAction Stop | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $latest) { throw "No registered recognition model was produced." }
    & (Join-Path $PSScriptRoot "activate-recognition-model.ps1") -ModelId $latest.Name
}
finally {
    Remove-Item Env:ISALA_NESTED_PREFLIGHT_APPROVED -ErrorAction SilentlyContinue
}
