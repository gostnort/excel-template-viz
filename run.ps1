# Excel Template Viz - NiceGUI
# Ctrl+C stops the server directly (no cmd batch Y/N prompt).
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$BootupDir = Join-Path $PSScriptRoot "bootup"
$VenvPy = Join-Path $BootupDir ".venv\Scripts\python.exe"

function Start-NiceGuiApp {
    # 优先直接用 bootup\.venv，避免 uv 与根目录旧 .venv 的 VIRTUAL_ENV 冲突
    if (Test-Path -LiteralPath $VenvPy) {
        & $VenvPy -m nicegui_ui.app
        return $LASTEXITCODE
    }
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
        uv run --project $BootupDir python -m nicegui_ui.app
        return $LASTEXITCODE
    }
    Write-Host "ERROR: bootup\.venv missing and uv not on PATH. Run install.bat first."
    return 1
}

$exitCode = Start-NiceGuiApp
exit $exitCode
