param(
    [string]$OutZip = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $OutZip) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutZip = Join-Path $ProjectRoot "..\autoquote-deploy-$stamp.zip"
}

$stage = Join-Path $env:TEMP "autoquote-pack-$(Get-Random)"
New-Item -ItemType Directory -Force -Path $stage | Out-Null
$dest = Join-Path $stage "自报项目"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
robocopy $ProjectRoot $dest /MIR /XD .acceptance_runtime .tmp .venv __pycache__ .pytest_cache .git .idea logs tests tmpd1r24uug _recovery_unzip node_modules /XF .server.lock .server.pid .env *.pyc *.zip *.bak-* *.pre_recover_*.bak /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }

# 服务器上保留运行时数据，不打进更新包
$dataDir = Join-Path $dest "data"
if (Test-Path $dataDir) {
    Remove-Item (Join-Path $dataDir "quotes.db") -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $dataDir "quotes.db-wal") -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $dataDir "quotes.db-shm") -Force -ErrorAction SilentlyContinue
    $uploads = Join-Path $dataDir "uploads"
    if (Test-Path $uploads) { Remove-Item $uploads -Recurse -Force -ErrorAction SilentlyContinue }
}

if (Test-Path $OutZip) { Remove-Item $OutZip -Force }
Compress-Archive -Path $dest -DestinationPath $OutZip -Force
Remove-Item $stage -Recurse -Force

Write-Host "已打包: $OutZip"
Write-Host "上传到服务器 ~/autoquote/ 后解压覆盖，再执行 bash 自报项目/scripts/redeploy_server.sh"
