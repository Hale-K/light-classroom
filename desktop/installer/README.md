# Windows 安装向导

`windows.iss` 将已有 PyInstaller 完整目录封装为中文安装程序，不重新构建应用。

日常打包请使用 `desktop/build.ps1`，支持联网、演示、普通、离线四种模式，
会重新构建程序并在成功后清理同类型旧版本。命令见 [桌面端说明](../README.md)。
直接编译此文件仅重新封装已有程序目录，不包含之后的源码修改。

安装范围为当前用户，普通版默认位置为 `%LOCALAPPDATA%\Programs\LightClassroom`。
桌面和开始菜单快捷方式使用 `%APPDATA%\LightClassroom` 作为工作目录，日志可由普通用户写入。
卸载仅移除应用文件，保留该用户数据目录。普通版/空白离线版首次启动创建本机数据库；演示包包含明确指定的 SQLite 快照。安装包不包含开发环境、模型服务密钥和源目录中的日志。

## 编译

使用 Inno Setup 6.2.2 或更新版本，准备经过签名验证的微软 WebView2 Bootstrapper，然后执行：

```powershell
pwsh -File desktop/build.ps1 -Mode normal
```

默认联网引导器为 `MicrosoftEdgeWebview2Setup.exe`；离线模式使用完整的
`MicrosoftEdgeWebView2RuntimeInstallerX64.exe`。脚本自动准备并检查微软签名。
微软下载入口：https://go.microsoft.com/fwlink/p/?LinkId=2124703

中文语言文件来自 Inno Setup 项目的 `is-6_2_2` 标签：
https://github.com/jrsoftware/issrc/blob/is-6_2_2/Files/Languages/Unofficial/ChineseSimplified.isl

## 安装行为

- Windows 10 1607 或更新版本，x64；检查 .NET Framework 4.6.2 或更新版本。
- 按微软推荐的 HKLM32/HKCU 注册表位置检测 WebView2；缺少时安装对应运行环境，离线模式无需联网下载。
- WebView2 未安装成功时，阻止继续安装并显示错误。
- 默认创建桌面快捷方式；完成页可选择立即启动。
- 联网模式读取打包时提供的服务器地址（可通过其独立数据目录的 `server.url` 覆盖）。
- 普通、演示和离线版固定使用本机数据，离线版内置完整 WebView2 安装器。

手工传入 `BundleDir` 时必须使用完整且当前有效的程序目录。旧构建目录会被自动清理。
