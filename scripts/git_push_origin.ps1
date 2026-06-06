# 推送 main 到 GitHub 官方地址（绕过本机 gitclone 镜像重写）
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host '=== 自动报价系统 · GitHub 推送 ===' -ForegroundColor Cyan
Write-Host ''

$globalInsteadOf = git config --global --get url.https://gitclone.com/github.com/.insteadof 2>$null
if ($globalInsteadOf) {
    Write-Host '检测到全局 Git 配置会把 GitHub 重写到 gitclone 镜像：' -ForegroundColor Yellow
    Write-Host "  url.https://gitclone.com/github.com/.insteadof = $globalInsteadOf" -ForegroundColor Yellow
    Write-Host '这会导致 Credential Manager 弹出 gitclone.com 登录框。' -ForegroundColor Yellow
    Write-Host '本脚本已临时忽略全局/系统 Git 配置，直连 GitHub 官方地址。' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '如需永久修复，可在 PowerShell 手动执行：' -ForegroundColor DarkYellow
    Write-Host '  git config --global --unset url.https://gitclone.com/github.com/.insteadof' -ForegroundColor DarkYellow
    Write-Host ''
}

$originUrl = git config --get remote.origin.url
if ($originUrl -match 'gitclone\.com') {
    $fixed = $originUrl -replace 'https://gitclone\.com/github\.com/', 'https://github.com/'
    Write-Host "origin 仍为镜像地址，正在改为 GitHub 官方：$fixed" -ForegroundColor Yellow
    git remote set-url origin $fixed
}

$env:GIT_CONFIG_GLOBAL = 'NUL'
$env:GIT_CONFIG_SYSTEM = 'NUL'

Write-Host '当前有效远程（已绕过 gitclone 重写）：' -ForegroundColor Cyan
git remote -v
Write-Host ''

Write-Host '待推送提交：' -ForegroundColor Cyan
git log origin/main..HEAD --oneline 2>$null
if ($LASTEXITCODE -ne 0) {
    git log -3 --oneline
}
Write-Host ''

Write-Host '正在推送到 GitHub origin/main ...' -ForegroundColor Cyan
Write-Host '若弹出 Git Credential Manager：' -ForegroundColor Yellow
Write-Host '  Username = GitHub 用户名（syperstart）' -ForegroundColor Yellow
Write-Host '  Password = GitHub Personal Access Token（不是登录密码）' -ForegroundColor Yellow
Write-Host '创建 Token：GitHub → Settings → Developer settings → Personal access tokens' -ForegroundColor Yellow
Write-Host ''

git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host "push 失败，退出码: $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ''
Write-Host '推送成功。' -ForegroundColor Green
git log -1 --format='最新提交: %H %s'
Write-Host "仓库地址: $(git config --get remote.origin.url)" -ForegroundColor Green
