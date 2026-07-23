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

function Test-DockerEngine {
    $previousPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 may promote native stderr to a terminating
        # error while the Docker named pipe is absent. Engine availability is
        # a normal probe result here, so suppress that stderr locally.
        $ErrorActionPreference = "SilentlyContinue"
        & docker info *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Get-EnvironmentSetting {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$DefaultValue
    )

    $processValue = [Environment]::GetEnvironmentVariable($Name)
    if (-not [string]::IsNullOrWhiteSpace($processValue)) {
        return $processValue
    }

    if (Test-Path -LiteralPath ".env") {
        $escapedName = [Regex]::Escape($Name)
        foreach ($line in Get-Content -LiteralPath ".env") {
            if ($line -match "^\s*$escapedName\s*=(.*)$") {
                $value = $Matches[1].Trim()
                if (
                    $value.Length -ge 2 -and
                    (($value.StartsWith('"') -and $value.EndsWith('"')) -or
                     ($value.StartsWith("'") -and $value.EndsWith("'")))
                ) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
                return $value
            }
        }
    }

    return $DefaultValue
}

function Sync-PostgresPassword {
    param([Parameter(Mandatory)][string[]]$ComposeArguments)

    Write-Host "Checking PostgreSQL persistent volume..." -ForegroundColor Cyan
    & docker @ComposeArguments up -d postgres
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL startup failed."
    }

    Wait-Until -Description "PostgreSQL readiness" -Timeout $TimeoutSeconds -Condition {
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "SilentlyContinue"
            & docker @ComposeArguments exec -T postgres pg_isready `
                --username paperagent --dbname paperagent *> $null
            return $LASTEXITCODE -eq 0
        }
        finally {
            $ErrorActionPreference = $previousPreference
        }
    }

    $password = Get-EnvironmentSetting `
        -Name "POSTGRES_PASSWORD" `
        -DefaultValue "paperagent-dev"
    if ([string]::IsNullOrWhiteSpace($password) -or $password.Contains("`r") -or $password.Contains("`n")) {
        throw "POSTGRES_PASSWORD must be a non-empty single-line value."
    }

    # POSTGRES_PASSWORD only initializes a new data directory. When an existing
    # named volume is reused, synchronize the database role without deleting
    # user data. SQL single quotes are escaped before piping the statement over
    # the container's trusted local socket.
    $escapedPassword = $password.Replace("'", "''")
    $sql = "ALTER ROLE paperagent PASSWORD '$escapedPassword';"
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $sql | & docker @ComposeArguments exec -T postgres psql `
            --username paperagent `
            --dbname paperagent `
            --set ON_ERROR_STOP=1 `
            --quiet
        $syncExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($syncExitCode -ne 0) {
        throw "Could not synchronize the PostgreSQL role password."
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker was not found. Install and start Docker Desktop first."
}

if (-not (Test-DockerEngine)) {
    $dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        throw "Docker Engine is not running and Docker Desktop was not found."
    }

    Write-Host "Starting Docker Desktop..." -ForegroundColor Cyan
    Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    Wait-Until -Description "Docker Engine startup" -Timeout $TimeoutSeconds -Condition {
        Test-DockerEngine
    }
}

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Created .env from .env.example" -ForegroundColor DarkGray
}

$composeArguments = @("compose", "--env-file", ".env", "-f", "infrastructure/docker/compose.yaml")
if ($WithModels) {
    $composeArguments += @("--profile", "models")
}

Sync-PostgresPassword -ComposeArguments $composeArguments

$composeArguments += @("up", "-d")
if (-not $NoBuild) {
    $composeArguments += "--build"
}

Write-Host "Starting PaperAgentSystem..." -ForegroundColor Cyan
& docker @composeArguments
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose startup failed."
}

Write-Host "Waiting for the model router, API and web frontend..." -ForegroundColor Cyan
Wait-Until -Description "model router readiness" -Timeout $TimeoutSeconds -Condition {
    Test-HttpEndpoint "http://127.0.0.1:8080/health/ready"
}
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
