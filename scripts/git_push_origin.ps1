param(
    [string]$Remote = "wdbeep",
    [string]$Branch = "autoquote-optimized-latest",
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "=== AutoQuote GitHub upload ===" -ForegroundColor Cyan
Write-Host ""

# Remove the machine-wide gitclone rewrite so Git talks to GitHub directly while
# still keeping Git Credential Manager available for authentication.
$gitcloneRewrite = git config --global --get url.https://gitclone.com/github.com/.insteadof 2>$null
if ($gitcloneRewrite) {
    Write-Host "Removing global gitclone rewrite: $gitcloneRewrite" -ForegroundColor Yellow
    git config --global --unset url.https://gitclone.com/github.com/.insteadof
}

$remoteUrl = git config --get "remote.$Remote.url" 2>$null
if (-not $remoteUrl) {
    throw "Remote '$Remote' does not exist. Add it first with: git remote add $Remote https://github.com/OWNER/REPO.git"
}

if ($remoteUrl -match "gitclone\.com") {
    $remoteUrl = $remoteUrl -replace "https://gitclone\.com/github\.com/", "https://github.com/"
    git remote set-url $Remote $remoteUrl
}

Write-Host "Remote: $Remote -> $remoteUrl" -ForegroundColor Cyan
Write-Host "Branch: $Branch" -ForegroundColor Cyan
Write-Host ""

$status = git status --porcelain
if ($status) {
    Write-Host "Changes found. Creating a commit before upload..." -ForegroundColor Yellow
    git add -A

    if (-not $Message) {
        $stamp = Get-Date -Format "yyyy-MM-dd HH:mm"
        $Message = "chore: auto upload optimized version $stamp"
    }

    git commit -m $Message
} else {
    Write-Host "No local file changes. Uploading the current latest commit." -ForegroundColor Green
}

Write-Host ""
Write-Host "Latest local commit:" -ForegroundColor Cyan
git log -1 --oneline
Write-Host ""

Write-Host "Uploading to GitHub..." -ForegroundColor Cyan
git push -u $Remote "HEAD:$Branch"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Upload failed. If Git asks for login, use your GitHub username and a Personal Access Token." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Upload complete." -ForegroundColor Green
git log -1 --format="Latest uploaded commit: %H %s"
Write-Host "Repository: $remoteUrl" -ForegroundColor Green
