$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$runId = Get-Date -Format "yyyyMMddHHmmssfff"
$homeTempRoot = Join-Path $HOME ".codex\memories\prune-mem-install"
$tmpRoot = Join-Path $homeTempRoot "install-check-$runId"
$tempDir = Join-Path $tmpRoot "temp"
$buildTracker = Join-Path $tmpRoot "build-tracker"

New-Item -ItemType Directory -Force -Path $homeTempRoot | Out-Null
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
New-Item -ItemType Directory -Force -Path $buildTracker | Out-Null

$env:TMP = $tempDir
$env:TEMP = $tempDir
$env:PIP_BUILD_TRACKER = $buildTracker

Push-Location $repoRoot
try {
    rtk python -m pip install --no-index --no-build-isolation --no-deps .
}
finally {
    Pop-Location
}
