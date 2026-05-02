param(
  [string]$Distro = "Ubuntu-24.04",
  [string]$ProjectDir = "/home/project/OverseasContentAsset-Automated-Production-System/content_asset_mvp",
  [string]$HostAddress = "0.0.0.0",
  [int]$Port = 8001
)

$ErrorActionPreference = "Stop"

Write-Host "Starting Content Asset MVP in WSL distro '$Distro'..."
Write-Host "Project: $ProjectDir"
Write-Host "URL: http://127.0.0.1:$Port/"

$command = @"
set -e
cd '$ProjectDir'
service postgresql start >/dev/null 2>&1 || true
. .venv/bin/activate
python -m app.web --host '$HostAddress' --port '$Port'
"@

wsl -d $Distro -- bash -lc $command
