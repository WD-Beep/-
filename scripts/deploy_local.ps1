param(
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        if ($line.StartsWith("export ")) { $line = $line.Substring(7).Trim() }
        $idx = $line.IndexOf("=")
        $key = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
        if ($key) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

function Get-EnvOrDefault {
    param([string]$Name, [string]$Default)
    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    return $value
}

Import-DotEnv (Join-Path $ProjectRoot ".env")

$frontHost = Get-EnvOrDefault "QUOTE_SERVER_HOST" "127.0.0.1"
$frontPort = [int](Get-EnvOrDefault "QUOTE_SERVER_PORT" "8776")
$adminHost = Get-EnvOrDefault "QUOTE_ADMIN_SERVER_HOST" "127.0.0.1"
$adminPort = [int](Get-EnvOrDefault "QUOTE_ADMIN_HTTP_PORT" "8080")

$ports = @($frontPort)
if ($adminPort -gt 0) { $ports += $adminPort }

function Get-BusyPortRows {
    param([int[]]$WantedPorts)
    $rows = @()
    try {
        $rows = Get-NetTCPConnection -State Listen -ErrorAction Stop |
            Where-Object { $WantedPorts -contains $_.LocalPort } |
            Select-Object LocalAddress, LocalPort, OwningProcess
    } catch {
        $rows = @()
    }
    if ($rows.Count -gt 0) { return $rows }

    $patterns = $WantedPorts | ForEach-Object { ":$_" }
    $netstat = netstat -ano
    foreach ($line in $netstat) {
        if ($line -notmatch "\sLISTENING\s+(\d+)\s*$") { continue }
        foreach ($pat in $patterns) {
            if ($line -like "*$pat*") {
                $parts = ($line -split "\s+") | Where-Object { $_ }
                if ($parts.Count -ge 5) {
                    $addr = $parts[1]
                    $portText = ($addr -split ":")[-1]
                    $rows += [PSCustomObject]@{
                        LocalAddress = $addr
                        LocalPort = [int]$portText
                        OwningProcess = [int]$parts[-1]
                    }
                }
                break
            }
        }
    }
    return $rows
}

$busy = Get-BusyPortRows -WantedPorts $ports

if ($busy) {
    Write-Host "Ports are already in use. Existing service was left untouched:"
    $busy | Format-Table -AutoSize
    Write-Host "Stop the listed process first, then rerun this script."
    exit 2
}

if (Test-Path -LiteralPath ".server.lock") {
    try {
        Remove-Item -LiteralPath ".server.lock" -Force -ErrorAction Stop
    } catch {
        Write-Host "Server lock is still held. Existing service was left untouched:"
        Write-Host $_.Exception.Message
        Write-Host "Stop the old python server process first, then rerun this script."
        exit 2
    }
}

New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$stdout = Join-Path $ProjectRoot "logs\server-8776.out.log"
$stderr = Join-Path $ProjectRoot "logs\server-8776.err.log"

if ($Foreground) {
    python server.py
    exit $LASTEXITCODE
}

$proc = Start-Process `
    -FilePath "python" `
    -ArgumentList @("server.py") `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru

Set-Content -LiteralPath ".server.pid" -Value ([string]$proc.Id) -Encoding ASCII
Start-Sleep -Seconds 3

Write-Host "Started auto-quote service."
Write-Host "Front: http://$frontHost`:$frontPort/"
Write-Host "Admin: http://$adminHost`:$adminPort/admin/login"
Write-Host "PID: $($proc.Id)"
Write-Host "Logs: $stdout ; $stderr"
