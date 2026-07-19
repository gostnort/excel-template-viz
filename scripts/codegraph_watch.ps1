# CodeGraph background watcher: keeps ~/.codegraph index warm on file save.
# Do NOT add --watch to Cursor MCP (mcp.json); MCP stdio and --watch conflict in one process.
# Usage (from repo root):  .\scripts\codegraph_watch.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "CodeGraph watcher for: $RepoRoot"
Write-Host "Stop with Ctrl+C."

npx -y @astudioplus/codegraph-mcp@latest `
  --watch `
  -w $RepoRoot `
  --exclude .venv `
  --exclude node_modules `
  --exclude exports `
  --exclude temp `
  --exclude models `
  --exclude paddle_ocr/models
