$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$installed = Join-Path $repoRoot "_skill_install_test"
$workspace = Join-Path $repoRoot ".tmp\verify-installed-skill"

Push-Location $repoRoot
try {
    if (Test-Path -LiteralPath $installed) {
        Remove-Item -LiteralPath $installed -Recurse -Force
    }
    if (Test-Path -LiteralPath $workspace) {
        Remove-Item -LiteralPath $workspace -Recurse -Force
    }

    rtk python .\scripts\install_skill.py --target $installed | Out-Host

    $env:PRUNE_MEM_SKILL_WORKSPACE = $workspace
    rtk python "$installed\scripts\session_start.py" --session-id verify-installed | Out-Host
    rtk python "$installed\scripts\session_end.py" "$repoRoot\examples\transcript.json" | Out-Host
    rtk python "$installed\scripts\run_prune_mem.py" report --emit | Out-Host
    Get-Content -LiteralPath (Join-Path $workspace "data\usage_eval.jsonl") | Out-Host
}
finally {
    Remove-Item Env:PRUNE_MEM_SKILL_WORKSPACE -ErrorAction SilentlyContinue
    Pop-Location
}
