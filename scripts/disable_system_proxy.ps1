# 强制关闭 Windows 系统代理（Clash / Vortex 手动或自动打开后会被计划任务再次关掉）
$regPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
Set-ItemProperty -Path $regPath -Name ProxyEnable -Value 0 -ErrorAction SilentlyContinue
