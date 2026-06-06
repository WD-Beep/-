# 首次 push / 日常同步到 GitHub（绕过本机 gitclone 镜像）
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

$env:GIT_CONFIG_GLOBAL = 'NUL'
$env:GIT_CONFIG_SYSTEM = 'NUL'

Write-Host '正在推送到 GitHub: origin/main ...' -ForegroundColor Cyan
Write-Host '若弹出登录窗口，请用 GitHub 账号 syperstart + Personal Access Token 完成授权。' -ForegroundColor Yellow

git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host "push 失败，退出码: $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host '推送成功。' -ForegroundColor Green
git log -1 --oneline
git remote -v
