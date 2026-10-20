$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run scripts/setup.ps1 first.' }
$taskTemp = Join-Path $projectRoot 'workspace\temp'
New-Item -ItemType Directory -Path $taskTemp -Force | Out-Null
$env:TEMP = $taskTemp
$env:TMP = $taskTemp
$existingApi = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue
$apiProcess = $null
if (-not $existingApi) {
  $apiProcess = Start-Process -FilePath $pythonExe -ArgumentList '-m','uvicorn','server.app:app','--host','127.0.0.1','--port','8010' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
} else {
  try { $existingHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8010/api/health' -TimeoutSec 5 } catch { throw 'Port 8010 is occupied by a different service. Choose a free API port in vite.config.ts and this script.' }
  if ($existingHealth.pilot -ne 'nowshera') { throw 'Port 8010 is occupied by a different service.' }
}
try { npm run dev -- --host 127.0.0.1 } finally { if ($apiProcess -and -not $apiProcess.HasExited) { Stop-Process -Id $apiProcess.Id } }
