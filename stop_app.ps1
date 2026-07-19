$ErrorActionPreference = "Stop"

$pidFile = Join-Path $PSScriptRoot ".streamlit-app.pid"
if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host "No saved Streamlit process was found."
    exit 0
}

$processId = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
$process = Get-Process -Id $processId -ErrorAction SilentlyContinue
if ($process) {
    Stop-Process -Id $processId
    Write-Host "Travel Packing Assistant stopped."
} else {
    Write-Host "The saved process is no longer running."
}
