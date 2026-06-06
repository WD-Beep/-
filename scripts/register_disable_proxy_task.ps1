$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'disable_system_proxy.ps1'
$taskName = 'AutoQuote-DisableSystemProxy'

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`""

# 登录立刻关一次
$t1 = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# 登录 2 分钟后再关（等 Clash / Vortex 启动完）
$t2 = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$t2.Delay = 'PT2M'

# 不再每 5 分钟轮询：会周期性弹出 PowerShell 黑窗；仅在登录时关两次系统代理即可

$settings = New-ScheduledTaskSettingsSet `
    -Hidden `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($t1, $t2) -Settings $settings -Force | Out-Null

Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -Name ProxyEnable -Value 0

# Clash 服务改为手动启动，避免开机自动开代理（要用翻墙时再手动开 Clash）
try {
    Set-Service -Name 'clash_verge_service' -StartupType Manual -ErrorAction Stop
    Write-Output 'clash_verge_service -> Manual'
} catch {
    Write-Output "clash_verge_service skip: $($_.Exception.Message)"
}

Write-Output "OK: task $taskName registered (logon + logon+2min only, no 5min poll)"
