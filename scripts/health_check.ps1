param(
    [string]$FrontBase = "http://127.0.0.1:8776",
    [string]$AdminBase = "http://127.0.0.1:8080",
    [string]$AdminUser = "admin",
    [string]$AdminPassword = "baibo"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Assert-Ok {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$front = Invoke-WebRequest -UseBasicParsing -Uri "$FrontBase/" -TimeoutSec 10
Assert-Ok ($front.StatusCode -eq 200) "front page is not healthy"

$status = Invoke-RestMethod -Uri "$FrontBase/api/llm/status" -TimeoutSec 10
Assert-Ok ($null -ne $status.provider) "front api /api/llm/status failed"

$loginPage = Invoke-WebRequest -UseBasicParsing -Uri "$AdminBase/admin/login" -TimeoutSec 10
Assert-Ok ($loginPage.StatusCode -eq 200) "admin login page is not healthy"

$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$loginBody = @{ username = $AdminUser; password = $AdminPassword } | ConvertTo-Json -Compress
$login = Invoke-RestMethod `
    -Uri "$AdminBase/admin-api/login" `
    -Method POST `
    -WebSession $session `
    -ContentType "application/json" `
    -Body $loginBody `
    -TimeoutSec 10
Assert-Ok ($login.ok -eq $true) "admin login api failed"

$stats = Invoke-RestMethod -Uri "$AdminBase/admin-api/stats" -WebSession $session -TimeoutSec 10
Assert-Ok ($null -ne $stats.total_quotes) "admin stats failed"

$priceStats = Invoke-RestMethod -Uri "$AdminBase/admin-api/prices/stats" -WebSession $session -TimeoutSec 10
Assert-Ok ($null -ne $priceStats.total_entries) "price feedback stats failed"

$quotes = Invoke-RestMethod `
    -Uri "$AdminBase/admin-api/quotes?page=1&page_size=5" `
    -WebSession $session `
    -TimeoutSec 10
Assert-Ok ($null -ne $quotes.items) "admin quote list failed"

Write-Host "OK front=$FrontBase admin=$AdminBase"
Write-Host "LLM provider=$($status.provider) model=$($status.model) enabled=$($status.enabled)"
Write-Host "Admin total_quotes=$($stats.total_quotes)"
Write-Host "Price KB total_entries=$($priceStats.total_entries) open_exceptions=$($priceStats.open_exceptions)"
