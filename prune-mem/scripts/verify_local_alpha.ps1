$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $repoRoot ".local\bin\prune-mem-local.cmd"
$skillRunner = Join-Path $repoRoot "skill\prune-mem-skill\scripts\run_prune_mem.py"
$workspace = Join-Path $repoRoot ".tmp\verify-local-alpha"
$exportPath = Join-Path $workspace "memory-export.json"

Push-Location $repoRoot
try {
    if (Test-Path -LiteralPath $workspace) {
        Remove-Item -LiteralPath $workspace -Recurse -Force
    }

    rtk python .\scripts\install_local.py | Out-Host

    & $launcher smoke --workspace (Join-Path $workspace "smoke") | Out-Host

    & $launcher extract-transcript --root (Join-Path $workspace "memory") --input .\examples\transcript.json --ingest --emit | Out-Host
    & $launcher recall --root (Join-Path $workspace "memory") --tag memory --tag communication --emit | Out-Host
    & $launcher report --root (Join-Path $workspace "memory") --emit | Out-Host
    & $launcher inspect --root (Join-Path $workspace "memory") --kind profile | Out-Host
    & $launcher inspect --root (Join-Path $workspace "memory") --kind memories --emit | Out-Host
    & $launcher explain --root (Join-Path $workspace "memory") --slot-key response_style --emit | Out-Host
    & $launcher export --root (Join-Path $workspace "memory") --output $exportPath | Out-Host
    & $launcher import --root (Join-Path $workspace "imported") --input $exportPath --emit | Out-Host
    & $launcher report --root (Join-Path $workspace "imported") --emit | Out-Host

    & $launcher evaluate-all --root (Join-Path $workspace "suite") --scenarios-dir .\examples\scenarios --emit | Out-Host

    rtk python $skillRunner extract-transcript --input .\examples\transcript.json --emit | Out-Host
}
finally {
    Pop-Location
}
