$ErrorActionPreference = "Stop"

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $pythonPath = $python.Source
} else {
    $bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (-not (Test-Path -LiteralPath $bundledPython)) {
        throw "Python was not found. Install Python 3.10+ or add python.exe to PATH."
    }
    $pythonPath = $bundledPython
}

& $pythonPath -m travel_packing.cli @args
