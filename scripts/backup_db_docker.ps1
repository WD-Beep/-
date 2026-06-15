param(
    [string]$OutputDir = $env:BACKUP_DIR,
    [string]$Service = "postgres"
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir "..")).Path
}

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return
    }
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -ne 2) {
            continue
        }
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($key -and [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($key, "Process"))) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

$repoRoot = Resolve-RepoRoot
Import-DotEnv (Join-Path $repoRoot ".env")

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = $env:BACKUP_DIR
}
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $repoRoot "backups"
}
if (-not [System.IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir = Join-Path $repoRoot $OutputDir
}
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$user = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "influencer" }
$dbName = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "influencer_intel" }
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupFile = Join-Path $OutputDir "influencer-intel-$timestamp.dump"

$docker = Get-Command "docker" -ErrorAction SilentlyContinue
if (-not $docker) {
    throw "Docker was not found in PATH. Install Docker Desktop or use scripts\backup_db.ps1 with pg_dump."
}

Write-Host "Starting Docker database backup..."
$containerId = (& docker compose ps -q $Service).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not resolve Docker Compose service '$Service'. Is Docker Desktop running?"
}
if ([string]::IsNullOrWhiteSpace($containerId)) {
    throw "Docker Compose service '$Service' is not running."
}

$containerFile = "/tmp/influencer-intel-$timestamp.dump"
$dumpOutput = & docker compose exec -T $Service pg_dump -U $user -d $dbName --format=custom --blobs --no-owner --no-privileges --file=$containerFile 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Docker pg_dump failed: $dumpOutput"
}

& docker cp "${containerId}:$containerFile" $backupFile
if ($LASTEXITCODE -ne 0) {
    throw "docker cp failed while copying backup to $backupFile"
}

& docker compose exec -T $Service rm -f $containerFile | Out-Null


if (-not (Test-Path $backupFile)) {
    throw "Backup command finished but no file was created."
}

$size = (Get-Item $backupFile).Length
Write-Host "Backup completed: $backupFile"
Write-Host "Size: $size bytes"
