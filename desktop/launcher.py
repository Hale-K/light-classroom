"""轻课堂桌面端启动器。

数据目录：Windows %APPDATA%/LightClassroom，macOS ~/Library/Application Support/LightClassroom。
数据库：数据目录内 SQLite（aiosqlite）；Redis 不启用（生成任务回退进程内队列）；
意图向量模型不随包分发（分类自动降级 Jev/兜底）。前端静态文件由后端同进程托管。
"""
from __future__ import annotations

import os
import json
import shutil
import socket
import sys
import time
from pathlib import Path


def app_data_dir(demo: bool = False) -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    data = base / ("LightClassroomDemo" if demo else "LightClassroom")
    (data / "uploads").mkdir(parents=True, exist_ok=True)
    return data


def install_demo_seed(data_dir: Path, seed_dir: Path) -> None:
    """首次启动复制演示快照；后续启动保留用户在演示库中的修改。"""
    database = data_dir / "light-classroom.db"
    if database.exists():
        return
    if not (seed_dir / "light-classroom.db").is_file():
        raise FileNotFoundError("演示数据库未随安装包提供")
    for name in ("storage", "uploads"):
        source = seed_dir / name
        if source.is_dir():
            shutil.copytree(source, data_dir / name, dirs_exist_ok=True)
    shutil.copyfile(seed_dir / "manifest.json", data_dir / "demo.json")
    staging = data_dir / "light-classroom.db.seed"
    shutil.copyfile(seed_dir / "light-classroom.db", staging)
    os.replace(staging, database)
    print("[desktop] 演示数据库和附件已复制")


def downloads_dir() -> Path:
    """返回当前 Windows 用户配置的下载目录，兼容 OneDrive/组策略重定向。"""
    if sys.platform == "win32":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            downloads_id = "{374DE290-123F-4565-9164-39C4925E467B}"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                configured, _ = winreg.QueryValueEx(key, downloads_id)
            resolved = Path(os.path.expandvars(configured)).expanduser()
            if resolved.is_dir():
                return resolved
        except (OSError, TypeError, ValueError):
            pass
    fallback = Path.home() / "Downloads"
    return fallback if fallback.is_dir() else Path.home()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def prepare_env(data_dir: Path, port: int) -> None:
    """在任何 app 模块导入之前固定桌面环境变量。"""
    os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{(data_dir / 'light-classroom.db').as_posix()}")
    os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:1/0")  # 不可达 → 任务队列回退进程内实现
    os.environ.setdefault("MINIO_ENDPOINT", "127.0.0.1:1")       # 桌面版 v1：课件云端存储不可用，仅本地功能
    # JWT 密钥首次启动生成并持久化，保证重启后已登录会话不失效
    secret_file = data_dir / "jwt_secret.key"
    if not secret_file.exists():
        import secrets
        secret_file.write_text(secrets.token_hex(32), encoding="utf-8")
    os.environ.setdefault("JWT_SECRET_KEY", secret_file.read_text(encoding="utf-8").strip())
    os.environ["LIGHT_DESKTOP"] = "1"
    os.environ["LIGHT_DESKTOP_PORT"] = str(port)
    uploads = data_dir / "uploads"
    os.environ.setdefault("LIGHT_UPLOAD_DIR", str(uploads))
    # 文件中心本地存储：导出/导入直接落盘，不依赖 MinIO
    os.environ.setdefault("STORAGE_LOCAL_DIR", str(data_dir / "storage"))
    # PyInstaller 打包后 multiprocessing 子进程需重新执行引导脚本
    os.environ.setdefault("LIGHT_BOOTSTRAP", sys.argv[0])
    demo_manifest = data_dir / "demo.json"
    if demo_manifest.is_file():
        # 演示版始终使用本机快照，避免继承开发机的在线数据库配置。
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(data_dir / 'light-classroom.db').as_posix()}"
        os.environ["DEFAULT_SCHOOL_CODE"] = json.loads(demo_manifest.read_text(encoding="utf-8"))["school_code"]
        os.environ["STORAGE_LOCAL_DIR"] = str(data_dir / "storage")
        os.environ["LIGHT_UPLOAD_DIR"] = str(uploads)


def mount_frontend(app, dist: Path) -> None:
    """前端构建产物由后端同进程托管；不存在时仅提供 API（开发模式用 Vite）。

    SPA 兜底路由注册在全部 API 路由之后：/api、/docs 优先匹配，
    其余路径（含 /scheduling 等前端深链接）回落 index.html。
    """
    if not dist.is_dir():
        print(f"[desktop] 前端产物缺失: {dist}，仅启动 API")
        return
    from fastapi.responses import FileResponse
    from starlette.requests import Request
    from starlette.routing import Route

    app.router.routes = [
        r for r in app.router.routes
        if not (getattr(r, "path", None) == "/" and "GET" in getattr(r, "methods", set()))
    ]

    def spa(request: Request):
        full_path = request.path_params.get("full_path", "")
        candidate = (dist / full_path.lstrip("/")).resolve()
        if full_path and candidate.is_file() and str(candidate).startswith(str(dist.resolve())):
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")

    app.router.routes.append(Route("/{full_path:path}", spa, methods=["GET"]))


class _DesktopBridge:
    """注入页面的桌面能力桥：文件下载走原生“另存为”对话框。

    pywebview 里 window.open 会把整个窗口导航走（没有网页语义的新标签页），
    因此前端检测到 window.pywebview 时，文件下载改走本桥。
    """

    def __init__(self, base_url: str = "") -> None:
        self._base = base_url.rstrip("/")
        self._window: "webview.Window | None" = None

    def attach(self, window: "webview.Window") -> None:
        self._window = window

    def save_file(self, url: str, filename: str = "download") -> str:
        import tempfile
        import urllib.request

        import webview

        if not url:
            return "无效的下载地址"
        if url.startswith("/"):
            # 相对地址按当前服务基址补全（页面代码过旧未补全时在此兜底）
            url = self._base + url
        if not url.startswith(("http://", "https://")):
            return "无效的下载地址"
        tmp_name = ""
        try:
            safe = filename.replace("/", "_").replace("\\", "_") or "download"
            tmp = tempfile.NamedTemporaryFile(delete=False, prefix="lc_", suffix="_" + safe)
            tmp.close()
            tmp_name = tmp.name
            with urllib.request.urlopen(url, timeout=300) as resp, open(tmp_name, "wb") as out:
                out.write(resp.read())
            target = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=str(downloads_dir()),
                save_filename=safe,
            ) if self._window else None
            if not target:
                os.remove(tmp_name)
                return "canceled"
            target = target[0] if isinstance(target, (list, tuple)) else target
            os.replace(tmp_name, str(target))
            return "ok"
        except Exception as exc:
            print(f"[desktop] save_file 失败: {exc!r}")
            if tmp_name:
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass
            return f"下载失败：{exc}"


def main() -> None:
    demo = "--demo" in sys.argv
    data_dir = app_data_dir(demo=demo)

    # 桌面包无控制台：stdout/stderr 落到数据目录日志（UTF-8），便于排障；必须最先设置
    log_file = data_dir / "launcher.log"
    sys.stdout = sys.stderr = open(log_file, "a", encoding="utf-8", buffering=1)
    print(f"--- launcher 启动 {time.strftime('%Y-%m-%d %H:%M:%S')} ---")

    # 连接服务器模式：数据目录放一个 server.url（内容为网页端地址，如 http://192.168.1.10:5176），
    # 窗口直接加载网页端；教师/超管/学生三端在登录页内切换（同一路由组）。
    # 文件不存在则走本机模式。
    server_file = data_dir / "server.url"
    if not demo and server_file.exists():
        target = server_file.read_text(encoding="utf-8").strip()
        if target:
            print(f"[desktop] 服务器模式: {target}")
            import webview
            bridge = _DesktopBridge(base_url=target)
            window = webview.create_window("轻课堂", target, width=1440, height=900,
                                           min_size=(1100, 700), text_select=True, js_api=bridge)
            bridge.attach(window)
            webview.start()
            return

    # backend 根目录：源码运行 = 仓库 backend/；打包 = _MEIPASS/app
    if getattr(sys, "frozen", False):
        backend_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        backend_root = Path(__file__).resolve().parent.parent / "backend"
    if demo:
        install_demo_seed(data_dir, backend_root / "demo")
    port = free_port()
    prepare_env(data_dir, port)
    sys.path.insert(0, str(backend_root))

    import uvicorn
    from app.main import app

    mount_frontend(app, backend_root / "frontend")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)

    import threading
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()


    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)

    url = f"http://127.0.0.1:{port}"
    print(f"[desktop] 轻课堂已启动: {url}（数据目录 {data_dir}）")
    try:
        import webview
        bridge = _DesktopBridge(base_url=url)
        window = webview.create_window("轻课堂", url, width=1440, height=900,
                                       min_size=(1100, 700), text_select=True, js_api=bridge)
        bridge.attach(window)
        webview.start()
    except Exception as exc:  # WebView2 缺失等窗口故障：回退系统浏览器，服务保持运行
        print(f"[desktop] 窗口创建失败（{exc!r}），回退浏览器模式", file=sys.stderr)
        import webbrowser
        webbrowser.open(url)
        try:
            thread.join()
        except KeyboardInterrupt:
            pass
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
