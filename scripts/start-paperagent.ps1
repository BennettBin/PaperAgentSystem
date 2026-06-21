[CmdletBinding()]
param(
    [switch]$NoBuild,
    [switch]$WithModels,
    [switch]$NoBrowser,
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Wait-Until {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$Condition,
        [Parameter(Mandatory)]
        [string]$Description,
        [int]$Timeout = 180
    )

    $deadline = (Get-Date).AddSeconds($Timeout)
    while ((Get-Date) -lt $deadline) {
        try {
            if (& $Condition) {
                return
            }
        }
        catch {
            # The service may still be starting.
        }
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for: $Description"
}

function Test-HttpEndpoint {
    param([Parameter(Mandatory)][string]$Uri)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 3
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker was not found. Install and start Docker Desktop first."
}

if (-not (docker info 2>$null)) {
    $dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        throw "Docker Engine is not running and Docker Desktop was not found."
    }

    Write-Host "Starting Docker Desktop..." -ForegroundColor Cyan
    Start-Process -FilePath $dockerDesktop
    Wait-Until -Description "Docker Engine startup" -Timeout $TimeoutSeconds -Condition {
        docker info 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    }
}

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Created .env from .env.example" -ForegroundColor DarkGray
}

$composeArguments = @("compose")
if ($WithModels) {
    $composeArguments += @("--profile", "models")
}
$composeArguments += @("up", "-d")
if (-not $NoBuild) {
    $composeArguments += "--build"
}

Write-Host "Starting PaperAgentSystem..." -ForegroundColor Cyan
& docker @composeArguments
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose startup failed."
}

Write-Host "Waiting for the API and web frontend..." -ForegroundColor Cyan
Wait-Until -Description "API readiness" -Timeout $TimeoutSeconds -Condition {
    Test-HttpEndpoint "http://127.0.0.1:8000/health/ready"
}
Wait-Until -Description "Web frontend" -Timeout $TimeoutSeconds -Condition {
    Test-HttpEndpoint "http://127.0.0.1:3000"
}

Write-Host ""
Write-Host "PaperAgentSystem is ready." -ForegroundColor Green
Write-Host "Web:       http://localhost:3000"
Write-Host "API docs:  http://localhost:8000/docs"
Write-Host "MinIO:    http://localhost:9001"

if (-not $NoBrowser) {
    Start-Process "http://localhost:3000"
    Start-Process "http://localhost:8000/docs"
}
