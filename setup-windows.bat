@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem 智衡轻课堂 Windows 初始化脚本
rem 作用：检查运行环境、启动 PostgreSQL/Redis、安装前后端依赖、初始化数据库结构
rem 注意：不会删除数据库，也不会覆盖已有 backend\.env

cd /d "%~dp0"
set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend-react"
set "COMPOSE=%BACKEND%\docker-compose.yml"
set "VENV=%BACKEND%\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"

echo.
echo ============================================================
echo   智衡轻课堂 - Windows 环境与数据库初始化
echo ============================================================
echo.

if not exist "%BACKEND%\app\main.py" (
  echo [失败] 未找到 backend\app\main.py，请从项目根目录运行本文件。
  exit /b 1
)
if not exist "%FRONTEND%\package.json" (
  echo [失败] 未找到 frontend-react\package.json，请检查项目目录。
  exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 (
  echo [失败] 未检测到 Docker Desktop。
  echo        请先安装并启动 Docker Desktop：https://www.docker.com/products/docker-desktop/
  exit /b 1
)
docker compose version >nul 2>&1
if errorlevel 1 (
  echo [失败] 当前 Docker 不支持 docker compose 命令，请升级 Docker Desktop。
  exit /b 1
)

set "PY_LAUNCHER="
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys; assert sys.version_info >= (3, 11), sys.version" >nul 2>&1
  if not errorlevel 1 set "PY_LAUNCHER=py -3"
)
if not defined PY_LAUNCHER (
  where python >nul 2>&1
  if not errorlevel 1 (
    python -c "import sys; assert sys.version_info >= (3, 11), sys.version" >nul 2>&1
    if not errorlevel 1 set "PY_LAUNCHER=python"
  )
)
if not defined PY_LAUNCHER (
  echo [失败] 未检测到 Python 3.11 或更高版本。
  echo        请安装 Python 3.11 或更高版本，并勾选 Add Python to PATH。
  exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
  echo [失败] 未检测到 Node.js。
  echo        请安装 Node.js 20.19+ 或 22+：https://nodejs.org/
  exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
  echo [失败] 未检测到 npm，请重新安装 Node.js。
  exit /b 1
)

if not exist "%BACKEND%\.env" (
  if not exist "%BACKEND%\.env.example" (
    echo [失败] backend\.env.example 不存在，无法生成配置文件。
    exit /b 1
  )
  copy /Y "%BACKEND%\.env.example" "%BACKEND%\.env" >nul
  echo [完成] 已从 .env.example 创建 backend\.env
) else (
  echo [跳过] backend\.env 已存在，保留现有配置
)

echo.
echo [1/5] 启动数据库依赖（PostgreSQL + Redis）...
docker compose -f "%COMPOSE%" up -d postgres redis
if errorlevel 1 (
  echo [失败] Docker 依赖启动失败，请检查 Docker Desktop 状态。
  exit /b 1
)

echo [等待] 等待 PostgreSQL 就绪...
set "POSTGRES_READY="
for /l %%i in (1,1,30) do (
  docker compose -f "%COMPOSE%" exec -T postgres pg_isready -U zhiheng -d zhiheng >nul 2>&1
  if not errorlevel 1 (
    set "POSTGRES_READY=1"
    goto :postgres_ready
  )
  timeout /t 2 /nobreak >nul
)
:postgres_ready
if not defined POSTGRES_READY (
  echo [失败] PostgreSQL 等待超时。
  docker compose -f "%COMPOSE%" ps
  exit /b 1
)
echo [完成] PostgreSQL 已就绪

echo.
echo [2/5] 创建或复用 Python 虚拟环境...
if not exist "%PYTHON%" (
  call %PY_LAUNCHER% -m venv "%VENV%"
  if errorlevel 1 (
    echo [失败] Python 虚拟环境创建失败。
    exit /b 1
  )
  echo [完成] 已创建 backend\.venv
) else (
  echo [跳过] backend\.venv 已存在
)

echo.
echo [3/5] 安装后端依赖...
pushd "%BACKEND%"
call "%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 (
  popd
  echo [失败] pip 升级失败，请检查网络或 Python 安装。
  exit /b 1
)
call "%PYTHON%" -m pip install -e ".[dev]"
if errorlevel 1 (
  popd
  echo [失败] 后端依赖安装失败。
  exit /b 1
)
popd
echo [完成] 后端依赖已安装

echo.
echo [4/5] 初始化数据库结构与基础字典...
pushd "%BACKEND%"
call "%PYTHON%" -m alembic -c alembic.ini upgrade head
if errorlevel 1 (
  popd
  echo [失败] Alembic 数据库迁移失败。
  echo        请检查 backend\.env 中的 DATABASE_URL 与 PostgreSQL 状态。
  exit /b 1
)
set "PYTHONPATH=%BACKEND%"
call "%PYTHON%" -c "import asyncio; from app.db.session import init_db; asyncio.run(init_db())"
if errorlevel 1 (
  popd
  echo [失败] 项目数据库初始化失败。
  exit /b 1
)
popd
echo [完成] 数据库结构、默认租户、学科字典已准备好

echo.
echo [5/5] 安装前端依赖...
pushd "%FRONTEND%"
call npm install
if errorlevel 1 (
  popd
  echo [失败] 前端依赖安装失败，请检查 Node.js 或网络。
  exit /b 1
)
popd
echo [完成] 前端依赖已安装

echo.
echo ============================================================
echo   初始化完成
echo ============================================================
echo   数据库：PostgreSQL（Docker，localhost:5432）
echo   缓存：  Redis（Docker，localhost:6379）
echo   后端：  cd backend ^&^& .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001
echo   前端：  cd frontend-react ^&^& npm run dev -- --port 5176
echo.
echo   默认开发租户和平台管理员配置请查看 backend\.env。
echo   本脚本可重复运行，不会删除已有数据库数据。
echo.
pause
exit /b 0
