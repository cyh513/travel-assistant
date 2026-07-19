$ErrorActionPreference = "Stop"

$candidates = @(
    (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
    (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
)

$systemPython = Get-Command python -ErrorAction SilentlyContinue
if ($systemPython) {
    $candidates += $systemPython.Source
}

$pythonPath = $null
foreach ($candidate in $candidates) {
    if (-not (Test-Path -LiteralPath $candidate)) {
        continue
    }
    & $candidate -c "import streamlit" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $pythonPath = $candidate
        break
    }
}

if (-not $pythonPath) {
    throw "No Python interpreter with Streamlit was found. Run: python -m pip install -r requirements.txt"
}

Write-Host "Using Python: $pythonPath"
Push-Location $PSScriptRoot
try {
    & $pythonPath -m streamlit run .\app.py `
        --server.headless=false `
        --browser.gatherUsageStats=false
} finally {
    Pop-Location
}
