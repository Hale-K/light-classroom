[CmdletBinding()]
param([switch]$Offline)
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$root = Join-Path $repo 'output/installer-prerequisites'
New-Item -ItemType Directory -Path $root -Force | Out-Null
$name = if ($Offline) { 'MicrosoftEdgeWebView2RuntimeInstallerX64.exe' } else { 'MicrosoftEdgeWebview2Setup.exe' }
$link = if ($Offline) { 'https://go.microsoft.com/fwlink/?linkid=2124701' } else { 'https://go.microsoft.com/fwlink/?LinkId=2124703' }
$target = Join-Path $root $name
$staging = "$target.download"
Invoke-WebRequest -Uri $link -OutFile $staging
$signature = Get-AuthenticodeSignature -LiteralPath $staging
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw 'Downloaded prerequisite does not have a valid Microsoft signature.'
}
Move-Item -LiteralPath $staging -Destination $target -Force
Write-Host "WebView2 prerequisite ready: $target"
