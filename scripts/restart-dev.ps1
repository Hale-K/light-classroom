# =============================================================================
#  ZhiHeng LightClassroom 开发环境 一键重启脚本
#  作用：杀掉 5176（前端Vite）/ 8001（后端Uvicorn）端口上的旧进程后，
#        分别在两个独立 PowerShell 窗口中干净启动，保证每个服务只留 1 份。
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

function Stop-PortOwner {
    param(
        [int]$Port,
        [string[]]$AllowedProcessNames,  # 只杀这些名字的进程，避免误杀
        [int]$MaxWaitMs = 8000
    )

    Write-Host "[port:$Port] 扫描占用进程..." -ForegroundColor DarkCyan

    try {
        $pids = @( Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
                   Where-Object { $_.State -ne 'TIME_WAIT' -and $_.State -ne 'CLOSE_WAIT' } |
                   Select-Object -ExpandProperty OwningProcess -Unique )
    } catch {
        # 老系统可能没有 Get-NetTCPConnection，回退 netstat 解析
        Write-Host "[port:$Port] 回退 netstat 解析..." -ForegroundColor DarkYellow
        $lines = netstat -ano | Select-String -Pattern "LISTENING"
        $pids = @()
        foreach ($l in $lines) {
            if ($l -match ":$Port\s+.*LISTENING\s+(\d+)\s*$") {
                $pids += [int]$matches[1]
            }
        }
    }

    if (-not $pids -or $pids.Count -eq 0) {
        Write-Host "[port:$Port] 未发现占用进程，跳过清理 ✅" -ForegroundColor Green
        return $true
    }

    $killedAny = $false
    foreach ($procId in $pids) {
        try {
            $proc = Get-Process -Id $procId -ErrorAction Stop
            $name = $proc.ProcessName
            $match = $false
            foreach ($ap in $AllowedProcessNames) {
                if ($name -like "*$ap*") { $match = $true; break }
            }
            if (-not $match) {
                Write-Host ("[port:$Port] 跳过 PID=$procId ($name)，不属于允许的进程名 " +
                    ($AllowedProcessNames -join "/")) -ForegroundColor DarkYellow
                continue
            }
            $memMB = [math]::Round($proc.WorkingSet64 / 1MB, 1)
            Write-Host ("[port:$Port] 终止 PID=$procId  $name  (WS=$memMB MB)") `
                -ForegroundColor Magenta
            Stop-Process -Id $procId -Force -ErrorAction Stop
            $killedAny = $true
        } catch {
            Write-Host "[port:$Port] PID=$procId 终止失败: $($_.Exception.Message)" `
                -ForegroundColor Red
        }
    }

    if (-not $killedAny) { return $true }

    # 等待端口真正释放
    $elapsed = 0
    $step = 300
    Write-Host "[port:$Port] 等待端口释放..." -ForegroundColor DarkCyan
    while ($elapsed -lt $MaxWaitMs) {
        Start-Sleep -Milliseconds $step
        $elapsed += $step
        $still = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
                  Where-Object { $_.State -ne 'TIME_WAIT' -and $_.State -ne 'CLOSE_WAIT' }
        if (-not $still) {
            Write-Host "[port:$Port] 端口已释放 ✅ (等待 $elapsed ms)" `
                -ForegroundColor Green
            return $true
        }
    }
    Write-Host "[port:$Port] ⚠ 等待超时，仍可能被占用，继续启动..." -ForegroundColor Yellow
    return $false
}

# ----------- 清理 -----------
Write-Banner "清理旧进程（只保留新启动 1 份）"

Stop-PortOwner -Port $FRONT_PORT -AllowedProcessNames @("node")
Stop-PortOwner -Port $BACK_PORT  -AllowedProcessNames @("python","pythonw")

# ----------- 启动后端 -----------
Write-Banner "启动后端 FastAPI @ $BACK_PORT" Magenta

# 默认隐藏窗口后台运行，日志写入 logs/；需要看窗口时加 -ShowWindows
$winStyle = if ($ShowWindows) { "Normal" } else { "Hidden" }
New-Item -ItemType Directory -Force -Path "$BACK_CWD\logs" | Out-Null
New-Item -ItemType Directory -Force -Path "$FRONT_CWD\logs" | Out-Null

$backCmd = @(
    "-NoExit",
    "-Command",
    "`$env:PYTHONPATH='$BACK_CWD'; " +
    "Set-Location '$BACK_CWD'; " +
    "& '$BACK_VENV_PY' -m uvicorn app.main:app --host 127.0.0.1 --port $BACK_PORT"
)

$bp = Start-Process -FilePath "powershell.exe" `
    -ArgumentList $backCmd -PassThru -WindowStyle $winStyle `
    -RedirectStandardOutput "$BACK_CWD\logs\dev-backend.out.log" `
    -RedirectStandardError  "$BACK_CWD\logs\dev-backend.err.log"

Write-Host "后端进程已启动 PID=$($bp.Id)" -ForegroundColor Green

# 给后端一点启动时间，避免前端先发请求 404
Write-Host "等待后端启动..." -ForegroundColor DarkCyan
Start-Sleep -Seconds 4

# ----------- 启动前端 -----------
Write-Banner "启动前端 Vite @ $FRONT_PORT" Blue

$frontCmd = @(
    "-NoExit",
    "-Command",
    "Set-Location '$FRONT_CWD'; " +
    "npx vite --port $FRONT_PORT --host 127.0.0.1"
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
Write-Host ""
Write-Host "服务窗口默认隐藏。日志: backend\logs\dev-backend.*.log / frontend-react\logs\dev-frontend.*.log" -ForegroundColor DarkGray
Write-Host "后续若需重启，再次运行本脚本即可，它会自动杀掉旧进程。" -ForegroundColor DarkGray
