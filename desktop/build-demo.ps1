# Compatibility entry point for existing demo builds.
[CmdletBinding()]
param([string]$SeedDir, [string]$CompilerPath, [switch]$SkipFrontendBuild, [switch]$OfflineRuntime)
& (Join-Path $PSScriptRoot 'build.ps1') -Mode demo @PSBoundParameters
