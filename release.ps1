# Maintainer tool (not shipped to colleagues). Builds dist\AT7-Monitor.zip and dist\version.json - upload BOTH to the same web folder.
# Example: .\release.ps1 -BaseUrl https://github.com/<org>/<repo>/releases/latest/download -Notes "Faster dashboard"
# Colleagues then set "update_url" in config.json to  <BaseUrl>/version.json  (the app checks it every 6 hours).
param([string]$BaseUrl = "https://github.com/Aqeelhusny/Activity-Track-7h-monitor/releases/latest/download", [string]$Notes = "")
$ErrorActionPreference = "Stop"
$ver = (Select-String -Path "$PSScriptRoot\core.py" -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
python "$PSScriptRoot\test_core.py"; if ($LASTEXITCODE) { throw "tests failed - not releasing" }
$dist = "$PSScriptRoot\dist"; New-Item -ItemType Directory -Force $dist | Out-Null
$zip = "$dist\AT7-Monitor.zip"; Remove-Item $zip -ErrorAction SilentlyContinue
$files = "monitor.py", "core.py", "updater.py", "ui.html", "requirements.txt", "install.ps1", "install.bat", "uninstall.ps1", "uninstall.bat", "README.md", "LICENSE", "test_core.py"
Compress-Archive -Path ($files | ForEach-Object { "$PSScriptRoot\$_" }) -DestinationPath $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
@{ version = $ver; url = "$($BaseUrl.TrimEnd('/'))/AT7-Monitor.zip"; sha256 = $hash; notes = $Notes } | ConvertTo-Json | Set-Content "$dist\version.json" -Encoding utf8
Write-Host "Built v$ver  sha256 $hash`nUpload dist\AT7-Monitor.zip and dist\version.json to $BaseUrl"
