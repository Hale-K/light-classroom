[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$KeepBundleDir,
    [Parameter(Mandatory)][string]$KeepWorkDir,
    [Parameter(Mandatory)][string]$KeepInstaller,
    [Parameter(Mandatory)][string]$KeepDesktopInstaller
)

$ErrorActionPreference = 'Stop'
$desktopSourceRoot = Split-Path $PSScriptRoot -Parent
$repo = Split-Path $desktopSourceRoot -Parent
$installerRoot = Join-Path $repo 'output/windows-installer'
$desktopRoot = [Environment]::GetFolderPath('Desktop')

function Resolve-ScopedPath([string]$Path, [string]$Root) {
    $resolved = (Resolve-Path -LiteralPath $Path).ProviderPath
    $resolvedRoot = (Resolve-Path -LiteralPath $Root).ProviderPath.TrimEnd('\', '/')
    if (-not $resolved.StartsWith($resolvedRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside packaging directory: $resolved"
    }
    if ((Get-Item -LiteralPath $resolved -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Refusing linked packaging path: $resolved"
    }
    return $resolved
}

$bundle = Resolve-ScopedPath $KeepBundleDir $desktopSourceRoot
$work = Resolve-ScopedPath $KeepWorkDir $desktopSourceRoot
$installer = Resolve-ScopedPath $KeepInstaller $installerRoot
$desktopInstaller = Resolve-ScopedPath $KeepDesktopInstaller $desktopRoot
$keepBundles = @($bundle)
$keepWorks = @($work)
$keepInstallers = @($installer)
$keepDesktopInstallers = @($desktopInstaller)
# Keep the latest successful package of each mode, not every historical version.
foreach ($mode in @('online', 'demo', 'normal', 'offline')) {
    $recordFile = Join-Path $installerRoot "latest-$mode.json"
    if (-not (Test-Path -LiteralPath $recordFile)) { continue }
    $record = Get-Content -LiteralPath $recordFile -Raw | ConvertFrom-Json
    if ($record.mode -ne $mode) { throw "Invalid latest-package record: $recordFile" }
    if (@($record.bundle, $record.work, $record.installer, $record.desktop) | Where-Object { -not $_ -or -not (Test-Path -LiteralPath $_) }) {
        Write-Warning "Latest $mode package was removed manually; skipping its outdated record."
        continue
    }
    $keepBundles += Resolve-ScopedPath $record.bundle $desktopSourceRoot
    $keepWorks += Resolve-ScopedPath $record.work $desktopSourceRoot
    $keepInstallers += Resolve-ScopedPath $record.installer $installerRoot
    $keepDesktopInstallers += Resolve-ScopedPath $record.desktop $desktopRoot
}
if (-not (Test-Path -LiteralPath (Join-Path $bundle 'LightClassroom/LightClassroom.exe') -PathType Leaf)) {
    throw 'Latest application bundle is missing; old packages will be preserved.'
}
foreach ($file in @($installer, $desktopInstaller)) {
    if ((Get-Item -LiteralPath $file).Length -eq 0) { throw "Empty installer: $file" }
}
if ((Get-FileHash -LiteralPath $installer).Hash -ne (Get-FileHash -LiteralPath $desktopInstaller).Hash) {
    throw 'Desktop copy differs from installer; old packages will be preserved.'
}

$tracked = @(& git -C $repo ls-files desktop)
if ($LASTEXITCODE -ne 0) { throw 'Cannot check tracked source files; cleanup aborted.' }
$removed = 0
foreach ($directory in Get-ChildItem -LiteralPath $desktopSourceRoot -Directory) {
    if ($directory.Name -notmatch '^(?:build|out)(?:\d+|-[0-9-]+)?$|^dist$') { continue }
    $target = Resolve-ScopedPath $directory.FullName $desktopSourceRoot
    if ($target -in ($keepBundles + $keepWorks)) { continue }
    $relativePrefix = 'desktop/' + $directory.Name + '/'
    if ($tracked | Where-Object { $_.StartsWith($relativePrefix, [StringComparison]::OrdinalIgnoreCase) }) {
        throw "Refusing to remove tracked sources: $target"
    }
    if (Get-ChildItem -LiteralPath $target -Force -Recurse | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } | Select-Object -First 1) {
        throw "Refusing directory containing links: $target"
    }
    if ($PSCmdlet.ShouldProcess($target, 'Delete old build output')) {
        Remove-Item -LiteralPath $target -Recurse -Force
        $removed++
    }
}

# New builds are grouped under artifacts/<mode>/<timestamp>.
$artifactsRoot = Join-Path $desktopSourceRoot 'artifacts'
if (Test-Path -LiteralPath $artifactsRoot) {
    foreach ($mode in @('online', 'demo', 'normal', 'offline')) {
        $modeRoot = Join-Path $artifactsRoot $mode
        if (-not (Test-Path -LiteralPath $modeRoot)) { continue }
        foreach ($directory in Get-ChildItem -LiteralPath $modeRoot -Directory) {
            if ($directory.Name -notmatch '^\d{8}-\d{6}(?:-\d{3})?$') { continue }
            $target = Resolve-ScopedPath $directory.FullName $desktopSourceRoot
            if ($keepBundles + $keepWorks | Where-Object { $_.StartsWith($target + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) }) { continue }
            $relativePrefix = "desktop/artifacts/$mode/$($directory.Name)/"
            if ($tracked | Where-Object { $_.StartsWith($relativePrefix, [StringComparison]::OrdinalIgnoreCase) }) {
                throw "Refusing to remove tracked sources: $target"
            }
            if (Get-ChildItem -LiteralPath $target -Force -Recurse | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } | Select-Object -First 1) {
                throw "Refusing directory containing links: $target"
            }
            if ($PSCmdlet.ShouldProcess($target, 'Delete old mode build output')) {
                Remove-Item -LiteralPath $target -Recurse -Force
                $removed++
            }
        }
    }
}

# Earlier builds also stored bundles alongside installer logs. Preserve test profiles and logs.
foreach ($directory in Get-ChildItem -LiteralPath $installerRoot -Directory) {
    if ($directory.Name -notmatch '^[a-z][a-z-]*-\d{8}-\d{6}$') { continue }
    foreach ($child in Get-ChildItem -LiteralPath $directory.FullName -Directory) {
        if ($child.Name -notin @('bundle', 'build', 'dist', 'pyinstaller-work', 'frontend-snapshot')) { continue }
        $target = Resolve-ScopedPath $child.FullName $installerRoot
        if ($target -in ($keepBundles + $keepWorks)) { continue }
        if (Get-ChildItem -LiteralPath $target -Force -Recurse | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } | Select-Object -First 1) {
            throw "Refusing directory containing links: $target"
        }
        if ($PSCmdlet.ShouldProcess($target, 'Delete archived build output')) {
            Remove-Item -LiteralPath $target -Recurse -Force
            $removed++
        }
    }
}

foreach ($file in Get-ChildItem -LiteralPath $installerRoot -Filter 'LightClassroom-Setup*.exe' -File -Recurse) {
    $target = Resolve-ScopedPath $file.FullName $installerRoot
    if ($target -in $keepInstallers) { continue }
    if ($PSCmdlet.ShouldProcess($target, 'Delete old installer')) {
        Remove-Item -LiteralPath $target -Force
        $removed++
    }
}
foreach ($file in Get-ChildItem -LiteralPath $desktopRoot -File) {
    if ($file.Name -notmatch '^(?:轻课堂(?:演示版|联网版|普通版|离线版).*|LightClassroom-Setup.*)\.exe$') { continue }
    $target = Resolve-ScopedPath $file.FullName $desktopRoot
    if ($target -in $keepDesktopInstallers) { continue }
    if ($PSCmdlet.ShouldProcess($target, 'Delete old desktop installer')) {
        Remove-Item -LiteralPath $target -Force
        $removed++
    }
}
Write-Host "Cleaned $removed old packaging outputs. Latest package and application data preserved."
