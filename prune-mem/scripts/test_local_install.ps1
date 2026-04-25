$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repoRoot
try {
    rtk python .\scripts\install_local.py
    .\.local\bin\prune-mem-local.cmd smoke --workspace .\.tmp\local-install-smoke
}
finally {
    Pop-Location
}
