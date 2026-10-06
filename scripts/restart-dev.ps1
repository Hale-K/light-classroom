# =============================================================================
#  ZhiHeng LightClassroom 开发环境 一键重启脚本
#  作用：杀掉 5176（前端Vite）/ 8001（后端Uvicorn）端口上的旧进程后，
#        分别在独立 PowerShell 窗口中干净启动，保证 API、前端和 Worker 各只留 1 份。
#  用法：在 PowerShell 中直接运行  .\restart-dev.ps1
#        加 -ShowWindows 参数可显示服务窗口；默认隐藏，日志在各服务 logs/ 下
# =============================================================================
param([switch]$ShowWindows)

$FRONT_PORT = 5176
$BACK_PORT  = 8001
$FRONT_CWD  = "e:\school\code\light-classroom\frontend-react"
$BACK_CWD   = "e:\school\code\light-classroom\backend"
$BACK_VENV_PY = "$BACK_CWD\.venv\Scripts\python.exe"

function Write-Banner([string]$msg, [string]$color = "Cyan") {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Gray
    Write-Host "  $msg" -ForegroundColor $color
    Write-Host ("=" * 70) -ForegroundColor Gray
}

function Get-ListenerOwners([int]$Port) {
    foreach ($line in (netstat -ano -p tcp)) {
        if ($line -match ":$Port\s+.*LISTENING\s+(\d+)\s*$") {
            [int]$matches[1]
        }
    }
}

function Stop-PortOwner {
    param([int]$Port, [string[]]$AllowedProcessNames, [int]$MaxWaitMs = 8000)
    $processes = @(Get-CimInstance Win32_Process)
    $owners = @(Get-ListenerOwners $Port | Select-Object -Unique)
    foreach ($ownerId in $owners) {
        $owner = $processes | Where-Object { $_.ProcessId -eq $ownerId }
        $targets = @($owner)
        # Uvicorn reload 父进程退出后，spawn 子进程仍持有监听句柄。
        if (-not $owner) {
            $targets = @($processes | Where-Object {
                $_.ParentProcessId -eq $ownerId -and
                $_.CommandLine -match 'multiprocessing.spawn' -and
                $_.Name -match '^python(w)?\.exe$'
            })
        }
        $targetIds = @()
        foreach ($target in $targets) {
            if (-not $target) { continue }
            $name = [System.IO.Path]::GetFileNameWithoutExtension($target.Name)
            if ($name -notin $AllowedProcessNames) {
                throw "端口 $Port 被非服务进程 $name 占用，停止重启。"
            }
            $targetIds += $target.ProcessId
        }
        do {
            $children = @($processes | Where-Object {
                $_.ParentProcessId -in $targetIds -and $_.ProcessId -notin $targetIds
            })
            $targetIds += @($children.ProcessId)
        } while ($children.Count -gt 0)
        foreach ($targetId in ($targetIds | Select-Object -Unique)) {
            Stop-Process -Id $targetId -Force -ErrorAction SilentlyContinue
        }
    }
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.ElapsedMilliseconds -lt $MaxWaitMs) {
        if (-not @(Get-ListenerOwners $Port).Count) { return }
        Start-Sleep -Milliseconds 300
    }
    throw "端口 $Port 尚未释放，停止启动，避免运行多份服务。"
}

function Stop-CeleryWorker {
    Write-Host "扫描旧 Celery Worker..." -ForegroundColor DarkCyan
    $workerProcesses = @(Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and
        $_.CommandLine -match '(?i)app\.workers\.celery_app' -and
        $_.CommandLine -match '(?i)\bworker\b' -and
        $_.CommandLine -match [regex]::Escape($BACK_CWD)
    })

    foreach ($processInfo in $workerProcesses) {
        try {
            Stop-Process -Id $processInfo.ProcessId -Force -ErrorAction Stop
            Write-Host "已终止旧 Worker PID=$($processInfo.ProcessId)" -ForegroundColor Magenta
        } catch {
            Write-Host "Worker PID=$($processInfo.ProcessId) 终止失败：$($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

function Stop-ProjectLaunchShells {
    Write-Host "扫描旧服务启动外壳..." -ForegroundColor DarkCyan
    $launchShells = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -in @("powershell.exe", "pwsh.exe", "cmd.exe") -and
        $_.CommandLine -and
        $_.CommandLine -match '(?i)light-classroom' -and
        $_.CommandLine -match '(?i)(uvicorn|vite)'
    })

    foreach ($processInfo in $launchShells) {
        try {
            Stop-Process -Id $processInfo.ProcessId -Force -ErrorAction Stop
            Write-Host "已终止旧启动外壳 PID=$($processInfo.ProcessId)" -ForegroundColor Magenta
        } catch {
            Write-Host "启动外壳 PID=$($processInfo.ProcessId) 终止失败：$($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

# ----------- 清理 -----------
Write-Banner "清理旧进程（只保留新启动 1 份）"

Stop-PortOwner -Port $FRONT_PORT -AllowedProcessNames @("node")
Stop-PortOwner -Port $BACK_PORT  -AllowedProcessNames @("python","pythonw")
Stop-CeleryWorker
Stop-ProjectLaunchShells

# ----------- 启动后端 -----------
Write-Banner "启动后端 FastAPI @ $BACK_PORT" Magenta

# 默认隐藏窗口后台运行，日志写入 logs/；需要看窗口时加 -ShowWindows
$winStyle = if ($ShowWindows) { "Normal" } else { "Hidden" }
New-Item -ItemType Directory -Force -Path "$BACK_CWD\logs" | Out-Null
New-Item -ItemType Directory -Force -Path "$FRONT_CWD\logs" | Out-Null

$backCmd = @(
    "-NoProfile",
    "-Command",
    "`$env:PYTHONPATH='$BACK_CWD'; " +
    "Set-Location '$BACK_CWD'; " +
    "& '$BACK_VENV_PY' -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port $BACK_PORT"
)

$bp = Start-Process -FilePath "powershell.exe" `
    -ArgumentList $backCmd -PassThru -WindowStyle $winStyle `
    -RedirectStandardOutput "$BACK_CWD\logs\dev-backend.out.log" `
    -RedirectStandardError  "$BACK_CWD\logs\dev-backend.err.log"

Write-Host "后端进程已启动 PID=$($bp.Id)" -ForegroundColor Green

# 给后端一点启动时间，避免前端先发请求 404
Write-Host "等待后端启动..." -ForegroundColor DarkCyan
Start-Sleep -Seconds 4

# ----------- 启动排课 Worker -----------
Write-Banner "启动 Celery Worker（scheduling, academic）" Yellow

# Windows 开发环境使用 solo pool，避免 prefork 与 Windows 进程模型不兼容。
$workerCmd = @(
    "-Command",
    "`$env:PYTHONPATH='$BACK_CWD'; `$env:PYTHONUTF8='1'; `$env:PYTHONIOENCODING='utf-8'; " +
    "Set-Location '$BACK_CWD'; " +
    "& '$BACK_VENV_PY' -m celery -A app.workers.celery_app:celery_app worker -Q scheduling,academic --loglevel=info --pool=solo"
)

$wp = Start-Process -FilePath "powershell.exe" `
    -ArgumentList $workerCmd -PassThru -WindowStyle $winStyle `
    -RedirectStandardOutput "$BACK_CWD\logs\dev-worker.out.log" `
    -RedirectStandardError  "$BACK_CWD\logs\dev-worker.err.log"

Write-Host "Celery Worker 已启动 PID=$($wp.Id)" -ForegroundColor Green

# ----------- 启动前端 -----------
Write-Banner "启动前端 Vite @ $FRONT_PORT" Blue

$frontCmd = @(
    "-NoProfile",
    "-Command",
    "Set-Location '$FRONT_CWD'; " +
    "npx vite --port $FRONT_PORT --host 127.0.0.1 --strictPort"
)

$fp = Start-Process -FilePath "powershell.exe" `
    -ArgumentList $frontCmd -PassThru -WindowStyle $winStyle `
    -RedirectStandardOutput "$FRONT_CWD\logs\dev-frontend.out.log" `
    -RedirectStandardError  "$FRONT_CWD\logs\dev-frontend.err.log"

Write-Host "前端进程已启动 PID=$($fp.Id)" -ForegroundColor Green

# ----------- 汇总 -----------
Write-Banner "启动完成" Green
Write-Host "前端:  http://127.0.0.1:$FRONT_PORT"
Write-Host "后端:  http://127.0.0.1:$BACK_PORT"
Write-Host "Worker: scheduling, academic"
Write-Host ""
Write-Host "服务窗口默认隐藏。日志: backend\logs\dev-backend.*.log / backend\logs\dev-worker.*.log / frontend-react\logs\dev-frontend.*.log" -ForegroundColor DarkGray
Write-Host "后续若需重启，再次运行本脚本即可，它会自动杀掉旧进程。" -ForegroundColor DarkGray
