; Build with ISCC /DBundleDir=... /DPrerequisiteDir=... /DInstallerOutput=... windows.iss
#ifndef BundleDir
  #define BundleDir "..\out9\LightClassroom"
#endif
#ifndef PrerequisiteDir
  #define PrerequisiteDir "..\..\output\installer-prerequisites"
#endif
#ifndef InstallerOutput
  #define InstallerOutput "..\..\output\windows-installer"
#endif
#ifndef InstallerName
  #define InstallerName "LightClassroom-Setup-x64-20261009-fix1"
#endif
#ifndef DemoMode
  #define DemoMode "0"
#endif
#ifndef PackageMode
  #define PackageMode "normal"
#endif
#ifndef OfflineRuntime
  #define OfflineRuntime "0"
#endif
#if OfflineRuntime == "1"
  #define RuntimeFile "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
#else
  #define RuntimeFile "MicrosoftEdgeWebview2Setup.exe"
#endif
#if DemoMode == "1"
  #define ProductName "轻课堂演示版"
  #define ProductDir "LightClassroomDemo"
  #define LaunchParameters "--demo"
  #ifndef GuideFile
    #define GuideFile "demo-guide.txt"
  #endif
#else
  #define ProductName "轻课堂"
  #define ProductDir "LightClassroom"
  #define LaunchParameters "--local"
  #ifndef GuideFile
    #define GuideFile "install-guide.txt"
  #endif
#endif
#if PackageMode == "online"
  #undef ProductName
  #undef ProductDir
  #undef LaunchParameters
  #define ProductName "轻课堂联网版"
  #define ProductDir "LightClassroomOnline"
  #define LaunchParameters "--online"
#elif PackageMode == "offline"
  #undef ProductName
  #undef ProductDir
  #undef LaunchParameters
  #define ProductName "轻课堂离线版"
  #if DemoMode == "1"
    #define ProductDir "LightClassroomOfflineDemo"
    #define LaunchParameters "--offline --demo"
  #else
    #define ProductDir "LightClassroomOffline"
    #define LaunchParameters "--offline"
  #endif
#endif

[Setup]
#if PackageMode == "online"
AppId={{F4A6147A-9D70-484D-AE41-BA3FE92D779C}
#elif PackageMode == "offline"
  #if DemoMode == "1"
AppId={{751F92E0-3094-453A-B195-9003AD1DF3EE}
  #else
AppId={{76C3ED1B-0153-489C-84C7-05C9F5FD900C}
  #endif
#elif DemoMode == "1"
AppId={{D2DD9B33-769B-44A7-8254-E6B8F3F19E78}
#else
AppId={{75DA4CF0-CDE4-4B33-8EA0-0BDA21B64BAF}
#endif
AppName={#ProductName}
AppVersion=0.1.0
AppVerName={#ProductName} 0.1.0
AppPublisher=轻课堂
DefaultDirName={localappdata}\Programs\{#ProductDir}
UsePreviousAppDir=no
DefaultGroupName={#ProductName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0.14393
OutputDir={#InstallerOutput}
OutputBaseFilename={#InstallerName}
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\LightClassroom.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
DisableDirPage=no
DisableProgramGroupPage=yes
InfoBeforeFile={#GuideFile}
CloseApplications=yes
RestartApplications=no
UninstallDisplayName={#ProductName}
SetupLogging=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[LangOptions]
DialogFontName=Microsoft YaHei UI
WelcomeFontName=Microsoft YaHei UI
TitleFontName=Microsoft YaHei UI
CopyrightFontName=Microsoft YaHei UI

[Messages]
WelcomeLabel1=欢迎安装轻课堂
WelcomeLabel2=轻课堂将安装到您的电脑，供您进行教务管理和排课。%n%n本试用版适用于 Windows 10（1607 或更新版本）和 Windows 11 的 64 位系统。%n%n点击“下一步”查看使用说明并选择安装位置。
FinishedHeadingLabel=轻课堂安装完成
#if PackageMode == "online"
FinishedLabel=请通过“轻课堂联网版”快捷方式打开程序，使用服务器上的账号登录。%n%n运行时需要连接学校服务器。服务器地址已随包配置，不会初始化本机学校数据库。
#elif DemoMode == "1"
FinishedLabel=请通过“轻课堂演示版”快捷方式打开程序。%n%n首次启动会复制演示数据库和附件，请稍候。%n%n教师端演示账号：13710617058，密码：123456。%n%n平台管理员账号：admin，密码：admin123456。
#else
FinishedLabel=您可以通过桌面或开始菜单中的“轻课堂”快捷方式打开程序。%n%n首次启动会自动创建本机数据库，可能需要等待片刻。%n%n首次登录请切换到“平台管理员”，账号 admin，密码 admin123456；登录后请修改密码。
#endif

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Dirs]
Name: "{userappdata}\{#ProductDir}"; Flags: uninsneveruninstall

[Files]
Source: "{#BundleDir}\LightClassroom.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BundleDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PrerequisiteDir}\{#RuntimeFile}"; Flags: dontcopy

[Icons]
Name: "{group}\{#ProductName}"; Filename: "{app}\LightClassroom.exe"; Parameters: "{#LaunchParameters}"; WorkingDir: "{userappdata}\{#ProductDir}"
Name: "{group}\卸载{#ProductName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#ProductName}"; Filename: "{app}\LightClassroom.exe"; Parameters: "{#LaunchParameters}"; WorkingDir: "{userappdata}\{#ProductDir}"; Tasks: desktopicon

[Run]
Filename: "{app}\LightClassroom.exe"; Parameters: "{#LaunchParameters}"; WorkingDir: "{userappdata}\{#ProductDir}"; Description: "启动{#ProductName}"; Flags: nowait postinstall skipifsilent

[Code]
const
  WebViewKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function HasWebView2: Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(HKLM32, WebViewKey, 'pv', Version);
  if Result then
    Result := (Version <> '') and (Version <> '0.0.0.0');
  if not Result then begin
    Result := RegQueryStringValue(HKCU, WebViewKey, 'pv', Version);
    if Result then
      Result := (Version <> '') and (Version <> '0.0.0.0');
  end;
end;

function InitializeSetup: Boolean;
var
  Release: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM32, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release);
  if Result then
    Result := Release >= 394802;
  if not Result then
    MsgBox('轻课堂需要 .NET Framework 4.6.2 或更新版本。请先安装系统更新或 .NET Framework 4.8，再重新运行安装程序。', mbError, MB_OK);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
begin
  Result := '';
  if HasWebView2 then
    Exit;
#if OfflineRuntime == "1"
  WizardForm.StatusLabel.Caption := '正在安装随包提供的 Microsoft WebView2 运行环境，无需联网…';
#else
  WizardForm.StatusLabel.Caption := '正在安装 Microsoft WebView2 运行环境，请保持网络连接…';
#endif
  ExtractTemporaryFile('{#RuntimeFile}');
  if not Exec(ExpandConstant('{tmp}\{#RuntimeFile}'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then begin
    Result := '无法启动 WebView2 安装程序。请安装 Microsoft Edge WebView2 Runtime 后重试。';
    Exit;
  end;
  if not HasWebView2 then
#if OfflineRuntime == "1"
    Result := 'WebView2 离线安装未成功（退出码 ' + IntToStr(ExitCode) + '）。请检查系统安装权限，或请管理员安装随包提供的运行环境后重试。';
#else
    Result := 'WebView2 运行环境未安装成功（退出码 ' + IntToStr(ExitCode) + '）。请检查网络连接，或请管理员安装 Microsoft Edge WebView2 Runtime 后重试。';
#endif
end;
