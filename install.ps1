param(
  [string]$CodexRoot = "$env:USERPROFILE\.codex",
  [switch]$SkipPythonDeps,
  [switch]$SkipBootstrap
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillSource = Join-Path $Root "prune-mem\skill\prune-mem-skill"
$VendorSrc = Join-Path $Root "prune-mem\src\prune_mem"
$SkillDestRoot = Join-Path $CodexRoot "skills"
$SkillDest = Join-Path $SkillDestRoot "prune-mem-skill"
$VendorDest = Join-Path $SkillDest "vendor\prune_mem"
$RulekitSrc = Join-Path $Root "codex-rulekit\src"
$BinDir = Join-Path $Root ".bin"
$CmdShim = Join-Path $BinDir "codex-rulekit.cmd"
$PsShim = Join-Path $BinDir "codex-rulekit.ps1"

function Resolve-PythonCommand {
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    return @{
      Executable = $python.Source
      InlineArgs = @()
    }
  }

  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    return @{
      Executable = $py.Source
      InlineArgs = @("-3")
    }
  }

  throw "Python launcher not found. Install Python 3.11+ first."
}

function Invoke-Python {
  param(
    [Parameter(Mandatory = $true)]
    [hashtable]$Python,
    [Parameter(Mandatory = $true)]
    [string[]]$Args,
    [hashtable]$ExtraEnv = @{}
  )

  $previousValues = @{}
  foreach ($key in $ExtraEnv.Keys) {
    $previousValues[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
    [Environment]::SetEnvironmentVariable($key, $ExtraEnv[$key], "Process")
  }

  try {
    & $Python.Executable @($Python.InlineArgs + $Args)
    if ($LASTEXITCODE -ne 0) {
      throw "Python command failed: $($Args -join ' ')"
    }
  }
  finally {
    foreach ($key in $ExtraEnv.Keys) {
      [Environment]::SetEnvironmentVariable($key, $previousValues[$key], "Process")
    }
  }
}

if (!(Test-Path -LiteralPath $SkillSource)) {
  throw "Missing prune-mem skill source: $SkillSource"
}

if (!(Test-Path -LiteralPath $VendorSrc)) {
  throw "Missing prune-mem package source: $VendorSrc"
}

if (!(Test-Path -LiteralPath $RulekitSrc)) {
  throw "Missing codex-rulekit source: $RulekitSrc"
}

$Python = Resolve-PythonCommand
$CmdPython = ('"{0}"' -f $Python.Executable)
if ($Python.InlineArgs.Count -gt 0) {
  $CmdPython = $CmdPython + " " + ($Python.InlineArgs -join " ")
}

if (!$SkipPythonDeps) {
  try {
    Invoke-Python -Python $Python -Args @("-c", "import yaml")
  }
  catch {
    Write-Output "Installing missing dependency: PyYAML"
    Invoke-Python -Python $Python -Args @("-m", "pip", "install", "PyYAML")
  }
}

New-Item -ItemType Directory -Force -Path $SkillDest | Out-Null
Get-ChildItem -LiteralPath $SkillSource -Force | ForEach-Object {
  Copy-Item -LiteralPath $_.FullName -Destination $SkillDest -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $VendorDest | Out-Null
Get-ChildItem -LiteralPath $VendorSrc -Force | ForEach-Object {
  Copy-Item -LiteralPath $_.FullName -Destination $VendorDest -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

$CmdShimContent = @"
@echo off
set "PYTHONPATH=%~dp0..\codex-rulekit\src"
$CmdPython -m codex_rulekit %*
"@
Set-Content -LiteralPath $CmdShim -Encoding ASCII -Value $CmdShimContent

$PsShimContent = @'
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Args
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$RulekitSrc = Join-Path $RepoRoot "codex-rulekit\src"
$python = Get-Command python -ErrorAction SilentlyContinue
if (!$python) {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    $env:PYTHONPATH = $RulekitSrc
    & $py.Source -3 -m codex_rulekit @Args
    exit $LASTEXITCODE
  }
  throw "Python launcher not found."
}

$env:PYTHONPATH = $RulekitSrc
& $python.Source -m codex_rulekit @Args
exit $LASTEXITCODE
'@
Set-Content -LiteralPath $PsShim -Encoding UTF8 -Value $PsShimContent

$bootstrapStatus = "skipped"
if (!$SkipBootstrap) {
  Invoke-Python `
    -Python $Python `
    -Args @("-m", "codex_rulekit", "bootstrap", "--root", $CodexRoot) `
    -ExtraEnv @{ PYTHONPATH = $RulekitSrc }
  $bootstrapStatus = "ok"
}

Write-Output "Installed prune-mem skill: $SkillDest"
Write-Output "Vendored prune-mem package: $VendorDest"
Write-Output "Created codex-rulekit shim: $CmdShim"
Write-Output "Created PowerShell shim: $PsShim"
Write-Output "Bootstrap status: $bootstrapStatus"
Write-Output "Use: .\.bin\codex-rulekit.cmd --help"
