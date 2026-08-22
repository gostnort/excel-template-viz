# Keep a warm CodeGraph index in a separate terminal.
# Uses --watch via codegraph-daemon. Do NOT pass --mcp (MCP is Cursor mcp.json only).
# Isolate this repo via HOME so the daemon never backfills other projects from
# the shared ~/.codegraph/graph.db. MCP must use the same HOME (see ~/.cursor/mcp.json).
$ErrorActionPreference = "Stop"

if ($PSScriptRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $RepoRoot = (Get-Location).Path
}

$RepoName = Split-Path $RepoRoot -Leaf
$IsolatedHome = Join-Path $env:USERPROFILE (Join-Path ".codegraph\workspaces" $RepoName)
New-Item -ItemType Directory -Force -Path $IsolatedHome | Out-Null
$env:HOME = $IsolatedHome
$env:CODEGRAPH_TELEMETRY = "off"

# Match ~/.cursor/mcp.json excludes, plus watcher-heavy dirs.
$Excludes = @(
    ".venv",
    "bootup/.venv",
    "node_modules",
    "exports",
    "temp",
    "models",
    "paddle_ocr/models",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".nicegui"
)

$NpxArgs = @(
    "-y",
    "--package", "@astudioplus/codegraph-mcp@latest",
    "codegraph-daemon",
    "-w", $RepoRoot
)
foreach ($dir in $Excludes) {
    $NpxArgs += @("--exclude", $dir)
}

# Let the daemon load BGE for incremental embeds of THIS repo only.
$npxCache = Join-Path $env:LOCALAPPDATA "npm-cache\_npx"
$pkg = Get-ChildItem $npxCache -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName "node_modules\@astudioplus\codegraph-mcp" } |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1
if ($pkg) {
    $NpxArgs += @("--extension-path", $pkg)
}

Write-Host "CodeGraph watch starting"
Write-Host ("repo=" + $RepoRoot)
Write-Host ("HOME=" + $IsolatedHome)
Write-Host ("db=" + (Join-Path $IsolatedHome ".codegraph\graph.db"))
Write-Host ("excludes=" + ($Excludes -join ", "))
if ($pkg) {
    Write-Host ("extension-path=" + $pkg)
    Write-Host "mode=codegraph-daemon --watch (isolated HOME, BGE embeds this repo only)"
} else {
    Write-Host "mode=codegraph-daemon --watch (isolated HOME; no extension-path found)"
}
& npx @NpxArgs
$exitCode = $LASTEXITCODE
if ($null -eq $exitCode) { $exitCode = 0 }
exit $exitCode