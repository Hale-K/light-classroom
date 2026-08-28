@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem 智衡轻课堂 Windows 傻瓜式安装入口
rem 会使用 winget 安装缺少的基础环境，然后执行 setup-windows.bat

cd /d "%~dp0"
set "ROOT=%~dp0"
set "SETUP=%ROOT%setup-windows.bat"

echo.
echo ============================================================
echo   智衡轻课堂 - Windows 一键安装
echo ============================================================
echo.

if not exist "%SETUP%" (
  echo [失败] 未找到 setup-windows.bat。
  pause
  exit /b 1
)

where winget >nul 2>&1
if errorlevel 1 (
  echo [失败] 未检测到 winget。
  echo        请更新 Windows App Installer，或使用 setup-windows.bat 手动初始化。
  pause
  exit /b 1
)

echo [1/4] 检查并安装 Python 3.11...
where py >nul 2>&1
if errorlevel 1 (
  winget install --id Python.Python.3.12 --exact --source winget --accept-source-agreements --accept-package-agreements
  if errorlevel 1 goto :install_failed
  set "PATH=%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%PATH%"
)

echo [2/4] 检查并安装 Node.js LTS...
where node >nul 2>&1
if errorlevel 1 (
  winget install --id OpenJS.NodeJS.LTS --exact --source winget --accept-source-agreements --accept-package-agreements
  if errorlevel 1 goto :install_failed
  set "PATH=%ProgramFiles%\nodejs;%PATH%"
)

echo [3/4] 检查并安装 Docker Desktop...
where docker >nul 2>&1
if errorlevel 1 (
  winget install --id Docker.DockerDesktop --exact --source winget --accept-source-agreements --accept-package-agreements
  if errorlevel 1 goto :install_failed
  set "PATH=%ProgramFiles%\Docker\Docker\resources\bin;%PATH%"
  echo [提示] Docker Desktop 已安装，请先启动 Docker Desktop，再按任意键继续。
  pause
)

echo [4/4] 开始配置项目并初始化数据库...
call "%SETUP%"
if errorlevel 1 goto :install_failed

echo.
echo [完成] 智衡轻课堂已安装并完成数据库初始化。
pause
exit /b 0

:install_failed
echo.
echo [失败] 基础环境安装失败，请确认网络、管理员权限和 winget 状态。
pause
exit /b 1
