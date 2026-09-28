$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtime = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtime)) {
    Write-Host 'First run: python -m venv .venv'
    Write-Host 'Then run: .\.venv\Scripts\python.exe -m pip install -r requirements.txt'
    exit 1
}
& $runtime (Join-Path $PSScriptRoot 'run_local.py')
