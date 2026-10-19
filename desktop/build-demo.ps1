# Compatibility entry point for existing demo builds.
[CmdletBinding()]
param([string]$SeedDir, [string]$CompilerPath, [switch]$SkipFrontendBuild, [switch]$OfflineRuntime,
      [switch]$Trial, [ValidateRange(0, 3650)][int]$TrialDays = 0)
& (Join-Path $PSScriptRoot 'build.ps1') -Mode demo @PSBoundParameters
