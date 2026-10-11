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
  #define DemoMode 0
#endif
#if DemoMode
  #define ProductName "轻课堂演示版"
  #define ProductDir "LightClassroomDemo"
  #define LaunchParameters "--demo"
  #define GuideFile "demo-guide.txt"
#else
  #define ProductName "轻课堂"
  #define ProductDir "LightClassroom"
  #define LaunchParameters ""
  #define GuideFile "install-guide.txt"
#endif

[Setup]
#if DemoMode
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
#if DemoMode
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
Source: "{#PrerequisiteDir}\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy

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
  WizardForm.StatusLabel.Caption := '正在安装 Microsoft WebView2 运行环境，请保持网络连接…';
  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then begin
    Result := '无法启动 WebView2 安装程序。请安装 Microsoft Edge WebView2 Runtime 后重试。';
    Exit;
  end;
  if not HasWebView2 then
    Result := 'WebView2 运行环境未安装成功（退出码 ' + IntToStr(ExitCode) + '）。请检查网络连接，或请管理员安装 Microsoft Edge WebView2 Runtime 后重试。';
end;
