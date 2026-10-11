# Windows 安装向导

`windows.iss` 将已有 PyInstaller 完整目录封装为中文安装程序，不重新构建应用。

安装范围为当前用户，默认位置为 `%LOCALAPPDATA%\Programs\LightClassroom`。
桌面和开始菜单快捷方式使用 `%APPDATA%\LightClassroom` 作为工作目录，日志可由普通用户写入。
卸载仅移除应用文件，保留该用户数据目录。安装包不包含开发环境、数据库、密钥和源目录中的日志。

## 编译

使用 Inno Setup 6.2.2 或更新版本，准备经过签名验证的微软 WebView2 Bootstrapper，然后执行：

```powershell
ISCC.exe /DBundleDir="E:\school\code\light-classroom\desktop\out9\LightClassroom" /DPrerequisiteDir="E:\school\code\light-classroom\output\installer-prerequisites" /DInstallerOutput="E:\school\code\light-classroom\output\windows-installer" desktop/installer/windows.iss
```

`PrerequisiteDir` 必须包含 `MicrosoftEdgeWebview2Setup.exe`。
微软下载入口：https://go.microsoft.com/fwlink/p/?LinkId=2124703

中文语言文件来自 Inno Setup 项目的 `is-6_2_2` 标签：
https://github.com/jrsoftware/issrc/blob/is-6_2_2/Files/Languages/Unofficial/ChineseSimplified.isl

## 安装行为

- Windows 10 1607 或更新版本，x64；检查 .NET Framework 4.6.2 或更新版本。
- 按微软推荐的 HKLM32/HKCU 注册表位置检测 WebView2；缺少时运行内置引导安装器，需要联网。
- WebView2 未安装成功时，阻止继续安装并显示错误。
- 默认创建桌面快捷方式；完成页可选择立即启动。
- 现有数据与 `server.url` 配置继续生效。

本次试用包基于 `out9` 产物，未对后续源码修改重新构建。
