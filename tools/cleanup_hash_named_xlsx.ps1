#Requires -Version 5.1
<#
  仅在「你指定的文件夹」内查找文件名像长十六进制/UUID 的 .xlsx（WPS 同步垃圾常见）。
  默认只预览，不加 -Delete 不会删任何东西。
  禁止对「自报项目\data」及其子目录执行（避免误删后台归档）。
  用法：
    .\tools\cleanup_hash_named_xlsx.ps1 -TargetDir "D:\某个WPS文件夹"
    .\tools\cleanup_hash_named_xlsx.ps1 -TargetDir "D:\某个WPS文件夹" -Delete
#>
param(
    [Parameter(Mandatory = $true)]
    [string] $TargetDir,
    [switch] $Delete,
    [switch] $Recurse
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $TargetDir)) {
    Write-Error "路径不存在: $TargetDir"
}
$resolved = (Resolve-Path -LiteralPath $TargetDir).Path
$normalized = $resolved.Replace("/", "\").TrimEnd("\")

$dataGuard = $normalized -match '\\自动报价旅行包\\acquireKnowledge\\自报项目\\data(\\|$)'
if ($dataGuard) {
    Write-Error "为安全起见，禁止对本项目 data 目录执行（后台归档在此）。请改用 WPS/其它目录路径。"
}

function Test-HashLikeBaseName([string] $baseName) {
    $stripped = $baseName -replace "-", ""
    return ($baseName.Length -ge 28 -and $stripped -match "^[a-fA-F0-9]+$")
}

$params = @{
    LiteralPath = $resolved
    File        = $true
    Filter      = "*.xlsx"
}
if ($Recurse) {
    $hits = Get-ChildItem @params -Recurse -ErrorAction SilentlyContinue
}
else {
    $hits = Get-ChildItem @params -ErrorAction SilentlyContinue
}

$candidates = @($hits | Where-Object { Test-HashLikeBaseName $_.BaseName })
if ($candidates.Count -eq 0) {
    Write-Host "未发现符合条件的文件（当前目录$(if ($Recurse) { '+子目录' } else { ''})）。"
    exit 0
}

Write-Host "---- 候选 $($candidates.Count) 个 ----"
$candidates | ForEach-Object { Write-Host $_.FullName }

if (-not $Delete) {
    Write-Host ""
    Write-Host "以上为预览。确认无误后追加 -Delete 才会删除。"
    exit 0
}

foreach ($f in $candidates) {
    Remove-Item -LiteralPath $f.FullName -Force
    Write-Host "已删除: $($f.FullName)"
}
Write-Host "完成，共删除 $($candidates.Count) 个。"
