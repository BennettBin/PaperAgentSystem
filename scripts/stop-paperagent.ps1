[CmdletBinding()]
param(
    [switch]$RemoveVolumes
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$arguments = @(
    "compose",
    "--env-file",
    ".env",
    "-f",
    "infrastructure/docker/compose.yaml",
    "--profile",
    "models",
    "down"
)
if ($RemoveVolumes) {
    $arguments += "--volumes"
}

& docker @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Failed to stop PaperAgentSystem."
}

Write-Host "PaperAgentSystem has stopped." -ForegroundColor Green
if ($RemoveVolumes) {
    Write-Host "Persistent Docker volumes were removed." -ForegroundColor Yellow
}
else {
    Write-Host "Persistent Docker volumes were kept. Use -RemoveVolumes only when you want to reset local data." -ForegroundColor DarkGray
}
