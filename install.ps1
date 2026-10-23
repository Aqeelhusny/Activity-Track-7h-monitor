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

# upgrade case: snapshot the database BEFORE touching anything (sqlite's own backup, safe while the app runs). Keeps the last 5.
if (Test-Path "$Dest\activity.db") {
    $bk = "$Dest\backup"; New-Item -ItemType Directory -Force $bk | Out-Null
    $oldVer = (Select-String "$Dest\core.py" -Pattern '^VERSION = "(.+)"' -ErrorAction SilentlyContinue).Matches.Groups[1].Value
    $file = "$bk\activity-$(Get-Date -Format yyyyMMdd-HHmmss)-v$oldVer.db"
    & $py -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" "$Dest\activity.db" $file
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $file)) { throw "Database backup failed - update cancelled, nothing was changed." }
    Get-ChildItem "$bk\activity-*.db" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 5 | Remove-Item
    Write-Host "Database backed up to $file"
}

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
    # moving an existing install (e.g. from the project folder): bring its data along, but never over data already in $Dest
    if ((Test-Path "$src\activity.db") -and -not (Test-Path "$Dest\activity.db")) {
        & $py -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" "$src\activity.db" "$Dest\activity.db"
        if ($LASTEXITCODE -ne 0) { throw "Could not copy the existing database." }
    }
    if ((Test-Path "$src\config.json") -and -not (Test-Path "$Dest\config.json")) { Copy-Item "$src\config.json" $Dest }
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
