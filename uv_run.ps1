# uv run with extras from bootup/.install_profile (ocr | ocr-gpu).
# Usage from repo root: .\uv_run.ps1 python -m paddle_ocr.main
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: uv not on PATH. Run install.bat first."
    exit 1
}

$BootupDir = Join-Path $PSScriptRoot "bootup"
$VenvPy = Join-Path $BootupDir ".venv\Scripts\python.exe"
$ProfileHelper = Join-Path $BootupDir "uv_profile.py"
$py = $VenvPy
if (-not (Test-Path -LiteralPath $py)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $py = "py"
    } else {
        $py = "python"
    }
}

$extra = @()
if (Test-Path -LiteralPath $ProfileHelper) {
    $raw = & $py $ProfileHelper --flags
    if ($raw) {
        $extra = @($raw.ToString().Trim() -split "\s+" | Where-Object { $_ })
    }
}

Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
if ($extra.Count -gt 0) {
    uv run --project $BootupDir @extra @args
} else {
    uv run --project $BootupDir @args
}
exit $LASTEXITCODE
