$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$taskTemp = Join-Path $projectRoot 'workspace\temp'
$taskCache = Join-Path $projectRoot 'workspace\cache'
New-Item -ItemType Directory -Path $taskTemp,$taskCache -Force | Out-Null
$env:TEMP = $taskTemp
$env:TMP = $taskTemp
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { python -m venv .venv; if ($LASTEXITCODE) { throw 'Python 3.11+ is required.' } }
& '.\.venv\Scripts\python.exe' -m pip install --cache-dir (Join-Path $taskCache 'pip') -r server/requirements.txt
if ($LASTEXITCODE) { throw 'Python dependencies failed to install.' }
npm ci --cache (Join-Path $taskCache 'npm')
if ($LASTEXITCODE) { throw 'Node dependencies failed to install.' }
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $projectRoot 'workspace\tools\browsers'
npx --no-install playwright install chromium --only-shell
if ($LASTEXITCODE) { throw 'Browser installation failed.' }
Write-Output 'Dependencies ready. Start scripts/dev.ps1. HEC-RAS/HMS runtimes are separate official downloads; see README.'
