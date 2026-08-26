. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId "27"
$env:ISALA_NESTED_PREFLIGHT_APPROVED = "1"
try {
    & (Join-Path $PSScriptRoot "evaluate-recognition-model.ps1") -Kind baseline
    & (Join-Path $PSScriptRoot "export-recognition-model.ps1")
    & (Join-Path $PSScriptRoot "evaluate-recognition-model.ps1") -Kind custom
    & (Join-Path $PSScriptRoot "compare-models.ps1")
}
finally {
    Remove-Item Env:ISALA_NESTED_PREFLIGHT_APPROVED -ErrorAction SilentlyContinue
}
