# Stops AT7 Monitor and removes autostart. Your data is kept unless you pass -Purge.
param([string]$Dest = "$env:LOCALAPPDATA\AT7Monitor", [switch]$Purge)
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like "*$Dest*monitor.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\AT7 Monitor.lnk" -ErrorAction SilentlyContinue
if ($Purge) { Start-Sleep 1; Remove-Item $Dest -Recurse -Force; Write-Host "Removed $Dest including your data." }
else { Write-Host "Stopped and removed autostart. Data kept in $Dest (run with -Purge to delete everything)." }
