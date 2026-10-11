# 轻课堂桌面端

Tauri 之前的轻量方案：PyInstaller 打包 FastAPI 后端 + pywebview 窗口，SQLite 本机存储。

## 两种使用模式

| 模式 | 开启方式 | 账号与数据 |
|---|---|---|
| **本机模式**（默认） | 数据目录不放 `server.url` | 数据在本机 SQLite（`%APPDATA%/LightClassroom/light-classroom.db`），首次启动仅有平台管理员（`admin` / `admin123456`，可在 .env 改） |
| **连接服务器模式** | 数据目录放 `server.url` 文件，内容为网页端地址（如 `http://192.168.1.10:5176`） | 窗口直接加载网页端，**账号、数据与网页端完全一致**；删除该文件即回到本机模式 |

数据目录：Windows `%APPDATA%/LightClassroom`，macOS `~/Library/Application Support/LightClassroom`。
排障日志：同目录 `launcher.log`。

## 本机模式的能力边界（v1）

- 生成任务队列回退进程内实现（无 Redis）；排课求解（OR-Tools）完整可用
- 课件云端存储（MinIO）不可用；附件/头像等本地上传走数据目录 uploads
- 意图向量分类不随包分发（BGE/torch 1GB+），助手分类自动走 Jev 或兜底

## 构建

前置：Node（前端构建）、Python 3.12+（backend/.venv 内已装 pyinstaller、pywebview、aiosqlite）。

```bash
# 1. 前端产物
cd frontend-react && npx vite build && cd ..

# 2. 打包（Windows 在 Windows 上打，macOS 必须在 macOS 上打——PyInstaller 不能交叉编译）
backend/.venv/Scripts/pyinstaller.exe desktop/light-classroom.spec --noconfirm \
  --distpath desktop/dist --workpath desktop/build   # Windows
# macOS:
# backend/.venv/bin/pyinstaller desktop/light-classroom.spec --noconfirm \
#   --distpath desktop/dist --workpath desktop/build

# 3. 产物：desktop/dist/LightClassroom/（整目录即绿色版；安装包用 Inno Setup / dmg 打薄壳）
```

CI 双平台自动构建见 `.github/workflows/desktop.yml`（tag 推送时上传 Windows/macOS 产物到 GitHub Releases）。

## 已知限制

- macOS 包必须在 macOS 上构建；分发需 Apple Developer 签名 + 公证，否则提示"已损坏"
- Windows SmartScreen 可能拦截未签名 exe（正式发行建议代码签名证书）
- 端口为随机分配，与本机 dev server（8001/5176）共存不冲突

## 零数据库依赖声明（面向普通用户）

桌面包**不依赖、不连接 PostgreSQL**：启动器把数据库固定为应用数据目录内的 SQLite
（`aiosqlite`，随包内置），Redis/RabbitMQ 不存在时任务队列自动回退进程内实现，
向量模型不随包分发。解压（或安装）即可用，无需任何环境配置。

## Windows 一键安装包

1. PyInstaller 出 `desktop/dist/LightClassroom/`（见上文构建）
2. 安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php) 后执行：
   `"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" desktop/installer.iss`
3. 产物 `desktop/installer/轻课堂-Setup-x64.exe`：免管理员权限、装用户目录、
   自动创建桌面快捷方式；卸载只删程序，用户数据保留

CI 推送 `desktop-v*` 标签时自动产出 Windows Setup.exe + macOS 包并发布到 GitHub Releases。
