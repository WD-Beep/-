param(
    [string]$Remote = "wdbeep",
    [string]$Branch = "autoquote-optimized-latest"
)

# Bug-fix / small-step workflow: push the CURRENT commit only.
# - Does NOT git add
# - Does NOT create commits
# - Use AFTER: verify -> git add (scoped files) -> git commit
#
# For manual full upload (git add -A + auto commit + push), use:
#   scripts/git_push_origin.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "=== AutoQuote push after fix ===" -ForegroundColor Cyan
Write-Host ""

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
    Write-Host "WARN: Uncommitted local changes remain (not included in this push):" -ForegroundColor Yellow
    Write-Host $status
    Write-Host ""
}

Write-Host "Latest local commit to push:" -ForegroundColor Cyan
git log -1 --oneline
Write-Host ""

Write-Host "Pushing HEAD (no new commit)..." -ForegroundColor Cyan
git push -u $Remote "HEAD:$Branch"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Push failed. Check GitHub auth (PAT) and network." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Push complete." -ForegroundColor Green
git log -1 --format="Uploaded commit: %H %s"
Write-Host "Repository: $remoteUrl" -ForegroundColor Green
