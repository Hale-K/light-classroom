# -*- mode: python ; coding: utf-8 -*-
"""轻课堂桌面端 PyInstaller 打包配置。

构建（在仓库 backend/ 上层目录执行）：
  pyinstaller desktop/light-classroom.spec --noconfirm
产物：dist/LightClassroom/（Windows: LightClassroom.exe；macOS: LightClassroom.app）
"""
import os
from pathlib import Path

REPO = Path(SPECPATH).resolve().parent
FRONTEND_DIST = Path(os.environ.get("LIGHT_FRONTEND_DIST_DIR", str(REPO / "frontend-react" / "dist"))).resolve()
BACKEND = REPO / "backend"

datas = []
# 演示数据只在显式指定时打包；包含学校快照的目录保存在 ignored output/。
demo_seed = os.environ.get("LIGHT_DEMO_SEED_DIR")
if demo_seed:
    seed = Path(demo_seed).resolve()
    if not (seed / "light-classroom.db").is_file() or not (seed / "manifest.json").is_file():
        raise ValueError("LIGHT_DEMO_SEED_DIR 缺少完整演示快照")
    datas.append((str(seed), "demo"))
if (FRONTEND_DIST / "index.html").is_file():
    datas.append((str(FRONTEND_DIST), "frontend"))
# 技能书正文（catalog 按 __file__ 相对路径读取 book/ 目录）
datas.append((str(BACKEND / "app" / "ai" / "skill" / "book"), "app/ai/skill/book"))

# ortools（排课求解内核）含原生 DLL，PyInstaller 默认收集不全，需整包收集
from PyInstaller.utils.hooks import collect_all
ortools_datas, ortools_binaries, ortools_hiddenimports = collect_all("ortools")
datas += ortools_datas

hiddenimports = [
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "aiosqlite", "anyio._backends._asyncio",
    "webview",
    "app.main", "app.db.session",
]
hiddenimports += ortools_hiddenimports

# 桌面版不随包分发：BGE 向量模型（torch 体积 1GB+，意图分类自动降级）、
# celery/prometheus 等服务端组件、测试与构建工具。
excludes = [
    "torch", "torchvision", "torchaudio", "sentence_transformers", "transformers", "tiktoken",
    "celery", "prometheus", "pytest", "matplotlib", "IPython", "jupyter",
    "tkinter", "unittest",
]

a = Analysis(
    [str(REPO / "desktop" / "launcher.py")],
    pathex=[str(BACKEND)],
    binaries=ortools_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LightClassroom",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(REPO / "desktop" / "icon.ico") if (REPO / "desktop" / "icon.ico").is_file() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LightClassroom",
)
