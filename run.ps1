# Excel Template Viz - NiceGUI
# Ctrl+C stops the server directly (no cmd batch Y/N prompt).
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$BootupDir = Join-Path $PSScriptRoot "bootup"
$VenvPy = Join-Path $BootupDir ".venv\Scripts\python.exe"
$ProfileHelper = Join-Path $BootupDir "uv_profile.py"

function Get-UvExtraArgs {
    # 中文注释: 按 .install_profile 拼 uv --extra ocr|ocr-gpu，避免 uv run 把 OCR extra 卸掉
    $py = $null
    if (Test-Path -LiteralPath $VenvPy) {
        $py = $VenvPy
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $py = "py"
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $py = "python"
    }
    if (-not $py) {
        return @()
    }
    if (-not (Test-Path -LiteralPath $ProfileHelper)) {
        return @()
    }
    $raw = & $py $ProfileHelper --flags
    if (-not $raw) {
        return @()
    }
    return @($raw.ToString().Trim() -split "\s+" | Where-Object { $_ })
}

function Start-NiceGuiApp {
    # 优先直接用 bootup\.venv，避免 uv 与根目录旧 .venv 的 VIRTUAL_ENV 冲突
    if (Test-Path -LiteralPath $VenvPy) {
        & $VenvPy -m nicegui_ui.app
        return $LASTEXITCODE
    }
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
        $extra = Get-UvExtraArgs
        if ($extra.Count -gt 0) {
            uv run --project $BootupDir @extra python -m nicegui_ui.app
        } else {
            uv run --project $BootupDir python -m nicegui_ui.app
        }
        return $LASTEXITCODE
    }
    Write-Host "ERROR: bootup\.venv missing and uv not on PATH. Run install.bat first."
    return 1
}

$exitCode = Start-NiceGuiApp
exit $exitCode
