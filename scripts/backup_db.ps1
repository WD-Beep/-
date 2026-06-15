param(
    [string]$OutputDir = $env:BACKUP_DIR,
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [switch]$PlainSql
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

function Convert-AsyncpgUrl {
    param([string]$Url)
    if ([string]::IsNullOrWhiteSpace($Url)) {
        return $Url
    }
    $converted = $Url -replace "^postgresql\+asyncpg://", "postgresql://"
    return $converted -replace "@postgres:", "@localhost:"
}

function Get-BackupConnection {
    if (-not [string]::IsNullOrWhiteSpace($DatabaseUrl)) {
        return Convert-AsyncpgUrl $DatabaseUrl
    }

    $user = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "influencer" }
    $password = $env:POSTGRES_PASSWORD
    $hostName = if ($env:POSTGRES_HOST -and $env:POSTGRES_HOST -ne "postgres") { $env:POSTGRES_HOST } else { "localhost" }
    $port = if ($env:POSTGRES_PORT) { $env:POSTGRES_PORT } else { "5432" }
    $dbName = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "influencer_intel" }

    if ([string]::IsNullOrWhiteSpace($password)) {
        throw "POSTGRES_PASSWORD or DATABASE_URL is required for backup."
    }

    return "postgresql://$user`:$password@$hostName`:$port/$dbName"
}

function Find-PgDump {
    $cmd = Get-Command "pg_dump" -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    return $null
}

$repoRoot = Resolve-RepoRoot
Import-DotEnv (Join-Path $repoRoot ".env")

if ([string]::IsNullOrWhiteSpace($DatabaseUrl)) {
    $DatabaseUrl = $env:DATABASE_URL
}
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

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$extension = if ($PlainSql) { "sql" } else { "dump" }
$backupFile = Join-Path $OutputDir "influencer-intel-$timestamp.$extension"
$connection = Get-BackupConnection
$pgDump = Find-PgDump

if (-not $pgDump) {
    throw "pg_dump was not found in PATH. Install PostgreSQL client tools, or run this script on a machine with pg_dump available."
}

$formatArgs = if ($PlainSql) { @() } else { @("--format=custom", "--blobs") }
$args = @(
    "--no-owner",
    "--no-privileges",
    "--file=$backupFile"
) + $formatArgs + @($connection)

Write-Host "Starting database backup..."
& $pgDump @args

if ($LASTEXITCODE -ne 0) {
    throw "pg_dump failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path $backupFile)) {
    throw "Backup command finished but no file was created."
}

$size = (Get-Item $backupFile).Length
Write-Host "Backup completed: $backupFile"
Write-Host "Size: $size bytes"
