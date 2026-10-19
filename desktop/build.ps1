[CmdletBinding()]
param(
    [ValidateSet('online', 'demo', 'normal', 'offline')][string]$Mode = 'demo',
    [Alias('Domain')][string]$ServerUrl,
    [string]$SeedDir,
    [string]$CompilerPath,
    [string]$PythonPath,
    [switch]$Trial,
    [ValidateRange(0, 3650)][int]$TrialDays = 0,
    [switch]$SkipFrontendBuild,
    [switch]$OfflineRuntime
)

$ErrorActionPreference = 'Stop'
if ($Trial -and -not $PSBoundParameters.ContainsKey('TrialDays')) { $TrialDays = 7 }
if ($Trial -and $TrialDays -eq 0) { throw '-Trial cannot be combined with -TrialDays 0.' }
$repo = Split-Path $PSScriptRoot -Parent
$python = if ($PythonPath) { (Resolve-Path -LiteralPath $PythonPath).ProviderPath } else { Join-Path $repo 'backend/.venv/Scripts/python.exe' }
$installerRoot = Join-Path $repo 'output/windows-installer'
$desktopRoot = [Environment]::GetFolderPath('Desktop', [Environment+SpecialFolderOption]::Create)
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$artifactDir = Join-Path $PSScriptRoot "artifacts/$Mode/$stamp"
$bundleDir = Join-Path $artifactDir 'bundle'
$workDir = Join-Path $artifactDir 'work'
$installerName = "LightClassroom-Setup-x64-$Mode-$stamp"
$label = @{ online = '联网版'; demo = '演示版'; normal = '普通版'; offline = '离线版' }[$Mode]
if ($TrialDays -gt 0) { $label += '-试用版'; $installerName += '-trial' }
$desktopFile = Join-Path $desktopRoot "轻课堂$label-$stamp.exe"
$hasDemo = $Mode -eq 'demo' -or ($Mode -eq 'offline' -and $SeedDir)
$hasOfflineRuntime = $Mode -eq 'offline' -or $OfflineRuntime

if ($Mode -eq 'online') {
    if ($ServerUrl) {
        $ServerUrl = $ServerUrl.Trim()
        if ($ServerUrl -notmatch '://') { $ServerUrl = "https://$ServerUrl" }
    }
    $serverUri = $null
    if (-not [Uri]::TryCreate($ServerUrl, [UriKind]::Absolute, [ref]$serverUri) -or
        $serverUri.Scheme -notin @('http', 'https') -or -not $serverUri.Host -or
        $serverUri.UserInfo -or $serverUri.Query -or $serverUri.Fragment) {
        throw 'Online package requires -ServerUrl https://your-school-domain or -Domain your-school-domain (no credentials, query or fragment).'
    }
    $ServerUrl = $serverUri.AbsoluteUri.TrimEnd('/')
} elseif ($ServerUrl) { throw '-ServerUrl is only allowed for online mode.' }
if ($Mode -in @('online', 'normal') -and $SeedDir) { throw 'Demo seed is only allowed for demo/offline mode.' }
if ($hasDemo) {
    if (-not $SeedDir) {
        $SeedDir = $env:LIGHT_DEMO_SEED_DIR
        if (-not $SeedDir) { $SeedDir = Join-Path $repo 'output/demo-seed-20261010' }
    }
    $SeedDir = (Resolve-Path -LiteralPath $SeedDir).ProviderPath
    foreach ($file in @('light-classroom.db', 'manifest.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $SeedDir $file) -PathType Leaf)) { throw "Missing demo seed: $file" }
    }
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Backend Python build environment is missing.' }
if (-not $CompilerPath) {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { $CompilerPath = $command.Source }
    else {
        $CompilerPath = @(
            (Join-Path $repo 'output/inno-compiler/app/ISCC.exe'),
            'C:/Program Files (x86)/Inno Setup 6/ISCC.exe',
            'C:/Program Files/Inno Setup 6/ISCC.exe'
        ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    }
}
if (-not $CompilerPath -or -not (Test-Path -LiteralPath $CompilerPath -PathType Leaf)) { throw 'Inno Setup compiler missing. Supply -CompilerPath.' }
$prerequisiteDir = Join-Path $repo 'output/installer-prerequisites'
$runtimeFile = if ($hasOfflineRuntime) { 'MicrosoftEdgeWebView2RuntimeInstallerX64.exe' } else { 'MicrosoftEdgeWebview2Setup.exe' }
$runtimePath = Join-Path $prerequisiteDir $runtimeFile
if (-not (Test-Path -LiteralPath $runtimePath -PathType Leaf)) {
    & (Join-Path $PSScriptRoot 'scripts/get-webview2.ps1') -Offline:$hasOfflineRuntime
}
$signature = Get-AuthenticodeSignature -LiteralPath $runtimePath
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw 'WebView2 prerequisite must have a valid Microsoft signature.'
}
New-Item -ItemType Directory -Path $installerRoot, $workDir -Force | Out-Null
$configFile = Join-Path $workDir 'desktop-package.json'
@{ mode = $Mode; demo = [bool]$hasDemo; server_url = $ServerUrl; trial_days = $TrialDays } | ConvertTo-Json | Set-Content -LiteralPath $configFile -Encoding utf8
$guideFile = Join-Path $workDir 'install-guide.txt'
$folder = @{ online = 'LightClassroomOnline'; demo = 'LightClassroomDemo'; normal = 'LightClassroom'; offline = 'LightClassroomOffline' }[$Mode]
if ($Mode -eq 'offline' -and $hasDemo) { $folder = 'LightClassroomOfflineDemo' }
$usage = if ($Mode -eq 'online') {
    "连接学校服务器：$ServerUrl`r`n请使用服务器账号登录。不会创建本机学校数据库；使用时需要连接服务器。"
} elseif ($hasDemo) {
    '包含示例学校与 SQLite 数据。演示账号：13710617058，密码：123456。平台管理员：admin，密码：admin123456。'
} else {
    '首次启动创建本机 SQLite 数据库。平台管理员：admin，密码：admin123456。登录后修改密码，再创建学校和人员。'
}
$runtimeNote = if ($hasOfflineRuntime) { '包含完整 WebView2 安装程序，安装时无需联网。' } else { '缺少 WebView2 时安装程序需要联网下载运行环境。' }
$localNote = if ($Mode -eq 'online') { '业务数据由学校服务器保存。' } else { '本机 SQLite、基础教务、排课和本地导出可离线使用。' }
$trialNote = if ($TrialDays -gt 0) { "试用期限：当前电脑用户首次启动试用客户端后 $TrialDays 天。到期将停止使用客户端，业务数据保留；请联系软件提供方获取正式版。重装不会重新计时。" } else { '此安装包未设置客户端试用期限。' }
@"
轻课堂$label 安装与使用说明

支持 Windows 10（1607 或更新版本）和 Windows 11 的 64 位系统。
无需安装 Python、Node.js、Docker 或数据库服务器。
$runtimeNote

$usage
$trialNote

数据和日志目录：%APPDATA%\$folder。重新安装保留已有数据，卸载保留数据。
$localNote
AI 助手需要配置模型服务并联网，本包未包含离线大模型。
"@ | Set-Content -LiteralPath $guideFile -Encoding utf8BOM
$oldSeed = $env:LIGHT_DEMO_SEED_DIR
$oldConfig = $env:LIGHT_DESKTOP_PACKAGE_CONFIG
$oldFrontend = $env:LIGHT_FRONTEND_DIST_DIR
$oldUtf8 = $env:PYTHONUTF8
Push-Location $repo
try {
    if (-not $SkipFrontendBuild) {
        Push-Location (Join-Path $repo 'frontend-react')
        try {
            & pnpm build
            if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed. Old packages preserved.' }
        } finally { Pop-Location }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $repo 'frontend-react/dist/index.html'))) { throw 'Frontend build output is missing.' }
    $env:LIGHT_DEMO_SEED_DIR = if ($hasDemo) { $SeedDir } else { $null }
    $env:LIGHT_DESKTOP_PACKAGE_CONFIG = $configFile
    $env:LIGHT_FRONTEND_DIST_DIR = Join-Path $repo 'frontend-react/dist'
    $env:PYTHONUTF8 = '1'
    & $python -m PyInstaller desktop/light-classroom.spec --noconfirm --distpath $bundleDir --workpath $workDir
    if ($LASTEXITCODE -ne 0) { throw 'Application build failed. Old packages preserved.' }
    & $CompilerPath "/DBundleDir=$bundleDir/LightClassroom" "/DPrerequisiteDir=$prerequisiteDir" "/DInstallerOutput=$installerRoot" "/DInstallerName=$installerName" "/DDemoMode=$([int][bool]$hasDemo)" "/DPackageMode=$Mode" "/DOfflineRuntime=$([int][bool]$hasOfflineRuntime)" "/DGuideFile=$guideFile" desktop/installer/windows.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed. Old packages preserved.' }
    $installerFile = Join-Path $installerRoot "$installerName.exe"
    Copy-Item -LiteralPath $installerFile -Destination $desktopFile
    if ((Get-FileHash -LiteralPath $installerFile).Hash -ne (Get-FileHash -LiteralPath $desktopFile).Hash) { throw 'Desktop copy failed. Old packages preserved.' }
    $record = @{ mode = $Mode; trial_days = $TrialDays; bundle = $bundleDir; work = $workDir; installer = $installerFile; desktop = $desktopFile }
    $record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $installerRoot "latest-$Mode.json") -Encoding utf8
    & (Join-Path $PSScriptRoot 'scripts/clean-packages.ps1') -KeepBundleDir $bundleDir -KeepWorkDir $workDir -KeepInstaller $installerFile -KeepDesktopInstaller $desktopFile
    Write-Host "Installer ready: $desktopFile"
} finally {
    $env:LIGHT_DEMO_SEED_DIR = $oldSeed
    $env:LIGHT_DESKTOP_PACKAGE_CONFIG = $oldConfig
    $env:LIGHT_FRONTEND_DIST_DIR = $oldFrontend
    $env:PYTHONUTF8 = $oldUtf8
    Pop-Location
}
