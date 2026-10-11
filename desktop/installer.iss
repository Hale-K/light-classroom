; 轻课堂 Windows 一键安装包（Inno Setup 6）
; 构建：先 PyInstaller 出 dist\LightClassroom，再执行
;   ISCC.exe desktop\installer.iss
; 产物：desktop\installer\轻课堂-Setup.exe（双击安装，无需管理员权限）

#define MyAppName "轻课堂"
#define MyAppVersion "2.0"
#define MyAppExe "LightClassroom.exe"

[Setup]
AppId={{8C6B2F1E-52B7-4A9E-9B4C-LIGHTCLASSROOM}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\LightClassroom
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
Compression=lzma2/max
SolidCompression=yes
OutputDir=installer
OutputBaseFilename=轻课堂-Setup-x64
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
WizardStyle=modern

[Files]
Source: "dist\LightClassroom\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载只删程序；用户数据（数据库/上传件）保留在 %APPDATA%\LightClassroom
Type: files; Name: "{app}\*"
