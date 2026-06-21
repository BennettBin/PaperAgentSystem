[CmdletBinding()]
param(
    [switch]$RemoveVolumes
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$arguments = @("compose", "--profile", "models", "down")
if ($RemoveVolumes) {
    $arguments += "--volumes"
}

& docker @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Failed to stop PaperAgentSystem."
}

Write-Host "PaperAgentSystem has stopped." -ForegroundColor Green
