# AT7 Monitor installer: per-user, no admin needed. Safe to re-run (upgrades in place, keeps your data and config).
param([string]$Dest = "$env:LOCALAPPDATA\AT7Monitor", [switch]$NoStart, [switch]$NoShortcut)
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot

function Find-Python {
    $out = try { & py -3 -c "import sys;print(sys.executable)" } catch {}
    if (-not $out) { $out = try { & python -c "import sys;print(sys.executable)" } catch {} }  # note: the Microsoft Store stub prints nothing useful
    $out = $out | Select-Object -First 1
    if ($out -and (Test-Path "$out")) { return "$out".Trim() }
}

$py = Find-Python
if (-not $py) {
    Write-Host "Python 3 not found - installing it with winget..."
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
    $py = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Select-Object -Last 1 -ExpandProperty FullName
}
if (-not $py) { throw "Python 3.9+ is required. Install it from https://www.python.org/downloads/ (tick 'Add to PATH') and run this again." }

# stop a running copy (upgrade case)
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like "*$Dest*monitor.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep 1

New-Item -ItemType Directory -Force $Dest | Out-Null
if ((Resolve-Path $src).Path -ne (Resolve-Path $Dest).Path) {
    if (Test-Path "$Dest\monitor.py") {  # keep the previous version so a bad update can be rolled back by copying these files back
        New-Item -ItemType Directory -Force "$Dest\previous" | Out-Null
        foreach ($f in "monitor.py", "core.py", "updater.py", "ui.html") { if (Test-Path "$Dest\$f") { Copy-Item "$Dest\$f" "$Dest\previous" -Force } }
    }
    foreach ($f in "monitor.py", "core.py", "updater.py", "ui.html", "requirements.txt", "README.md", "uninstall.ps1", "uninstall.bat", "test_core.py") {
        if (Test-Path "$src\$f") { Copy-Item "$src\$f" $Dest -Force }
    }
    foreach ($f in Get-ChildItem "$src\activity.db*", "$src\config.json" -ErrorAction SilentlyContinue) {  # moving an existing install: bring its data along
        if (-not (Test-Path "$Dest\$($f.Name)")) { Copy-Item $f.FullName $Dest }
    }
}

$venvPy = "$Dest\.venv\Scripts\pythonw.exe"
if (-not (Test-Path $venvPy)) { & $py -m venv "$Dest\.venv" }
& "$Dest\.venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r "$Dest\requirements.txt"

if (-not $NoShortcut) {
    $startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
    Remove-Item "$startup\ActivityMonitor.lnk" -ErrorAction SilentlyContinue   # name used before the AT7 rename
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut("$startup\AT7 Monitor.lnk")
    $s.TargetPath = $venvPy
    $s.Arguments = '"' + "$Dest\monitor.py" + '"'
    $s.WorkingDirectory = $Dest
    $s.Save()
}
if (-not $NoStart) { Start-Process $venvPy "`"$Dest\monitor.py`"" -WorkingDirectory $Dest }

Write-Host "`nAT7 Monitor installed in $Dest"
Write-Host "It starts automatically each time you sign in to Windows. Dashboard: http://127.0.0.1:8787 (double-click the widget)."
