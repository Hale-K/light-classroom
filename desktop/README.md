# 轻课堂客户端打包

Windows 打包统一使用 `desktop/build.ps1`。脚本会重新构建前端和客户端，生成安装器，复制到桌面，最后清理同类型旧包。不会覆盖用户的数据库或重置已有账号密码。

## 四种版本

| 参数 | 业务数据 | WebView2 安装方式 | 默认数据目录（位于 `%APPDATA%`） |
|---|---|---|---|
| `online` 联网版 | 学校服务器，打包时必须提供域名 | 缺少时联网安装 | `LightClassroomOnline`（配置与日志） |
| `demo` 演示版 | 内置学校快照，本机 SQLite | 缺少时联网安装 | `LightClassroomDemo` |
| `normal` 普通版 | 本机 SQLite，不带演示学校数据 | 缺少时联网安装 | `LightClassroom` |
| `offline` 离线版 | 本机 SQLite，默认不带演示数据 | 内置完整运行环境安装器 | `LightClassroomOffline` |

普通版和演示版的基础教务、排课、本地导出也可离线运行；离线版还包含安装依赖。所有版本均未内置离线大模型，AI 助手需要配置模型服务。联网版使用学校服务器账号，本机超管账号不适用于服务器登录。

## 常用命令

在项目根目录用 Windows PowerShell 7 执行：

```powershell
# 联网版：替换为自己的学校域名，默认 HTTPS。
pwsh -File desktop/build.ps1 -Mode online -Domain "school.example.com"
# 校内 HTTP 服务或含路径的地址请显式提供完整 URL。
pwsh -File desktop/build.ps1 -Mode online -ServerUrl "http://192.168.1.10:8001"
# 演示版、普通版、离线版。
pwsh -File desktop/build.ps1 -Mode demo
pwsh -File desktop/build.ps1 -Mode normal
pwsh -File desktop/build.ps1 -Mode offline
# 带学校快照的离线版（数据目录为 LightClassroomOfflineDemo）。
pwsh -File desktop/build.ps1 -Mode offline -SeedDir "E:/path/to/demo-seed"
# 演示版内置完整离线安装依赖。
pwsh -File desktop/build.ps1 -Mode demo -OfflineRuntime
```

`build-demo.ps1` 仅为兼容入口，等同于 `build.ps1 -Mode demo`。联网版不填写域名会立即报错；不允许在服务器地址中夹带账号、密码、查询参数或片段。普通版和离线版不会读取其他版本的 `server.url`。

## 首次登录与账号保存

普通版和空白离线版首次启动会初始化平台超管：**账号 `admin`，密码 `admin123456`**。在登录页选择“平台管理员”，登录后可创建学校和校长账号，再进入学校配置人员与课程。

演示快照也包含启用的上述平台超管；示例学校账号为 `13710617058`，密码 `123456`。演示账号属于学校端，不是平台超管。

超管账号和密码哈希保存在本机 SQLite 数据库 `light-classroom.db` 中。重启、更新和卸载均保留用户数据；改过密码后继续使用新密码，重新安装不会将其恢复成默认密码。首次复制演示快照后也不会覆盖用户修改。

## 构建环境与参数

需要 Node.js/pnpm、后端 Python 环境（默认 `backend/.venv/Scripts/python.exe`）和 Inno Setup。桌面依赖列在 `requirements-build.txt`。

- `-CompilerPath`：指定 Inno Setup 编译器；默认查找 PATH、常见安装位置或 `output/inno-compiler/app/ISCC.exe`。
- `-PythonPath`：指定其他 Python 构建环境，供 CI 或自定义环境使用。
- `-SeedDir`：包含 `manifest.json`、`light-classroom.db` 及可选附件的快照目录；演示版默认 `output/demo-seed-20261010`。
- `-OfflineRuntime`：任何类型均可内置完整 WebView2 安装器；离线版自动启用。
- `-SkipFrontendBuild`：复用已有前端产物；仅在明确不需要重新构建前端时使用。

首次准备安装依赖需要下载微软运行环境，后续复用缓存并验证微软签名。离线安装器使用完整 x64 WebView2 安装程序。支持范围和安装条件由 `installer/windows.iss` 检查：Windows 10 1607 或更新版本/Windows 11 x64，.NET Framework 4.6.2 或更新版本。分发的应用尚未配置代码签名。

## 目录与产物

```text
desktop/
  build.ps1                    统一打包入口
  build-demo.ps1               旧演示命令兼容入口
  launcher.py                  客户端启动与模式选择
  light-classroom.spec         PyInstaller 配置
  export_demo.py               导出演示快照
  installer/                  当前中文安装器及说明
  scripts/                    运行环境下载、旧包清理
  tests/                      模式测试
  legacy/                     已停用的旧安装配置
  artifacts/<类型>/<时间>/     程序目录与构建缓存（不入库）
```

最终 EXE 保存到桌面和 `output/windows-installer`。该目录的 `latest-<类型>.json` 记录最新成功包。每种类型各保留最新一套；新包失败或复制不完整时不清理旧包。数据库种子、模板、已安装程序和用户数据不属于清理范围。

清理脚本为 `scripts/clean-packages.ps1`，支持 `-WhatIf` 预览。旧 `buildN`、`outN`、`dist` 输出会在新包成功后清理。不要手工删除最新记录指向的程序目录，再用该记录重新封装安装器。

## CI 与 macOS

`.github/workflows/desktop.yml` 的 Windows 构建使用统一入口生成普通版；macOS 使用 PyInstaller 生成压缩包。可手动触发工作流，`desktop-v*` 标签触发 Release 发布。本次未实际运行云端工作流。

macOS 包必须在 macOS 上构建，正式分发需要签名和公证。Windows 四种模式的一键安装脚本不能在 Mac 上直接执行。

WebView2 官方分发说明：https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution
