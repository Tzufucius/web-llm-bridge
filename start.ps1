[CmdletBinding()]
param(
    [string]$Python,
    [switch]$Setup,
    [switch]$CheckOnly,
    [switch]$BrokerOnly,
    [switch]$StopBroker
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$runtimeDir = Join-Path $root "runtime"
$pidFile = Join-Path $runtimeDir "broker.pid"
$stdoutLog = Join-Path $runtimeDir "broker.stdout.log"
$stderrLog = Join-Path $runtimeDir "broker.stderr.log"
$extensionDir = Join-Path $root "extension"

function Resolve-Python {
    if ($Python) {
        return (Get-Command $Python -ErrorAction Stop).Source
    }

    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }

    return (Get-Command python -ErrorAction Stop).Source
}

function Test-BrokerPort {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync("127.0.0.1", 8766)
        return $task.Wait(300) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Stop-OwnedBroker {
    if (-not (Test-Path -LiteralPath $pidFile)) {
        Write-Host "没有由 start.ps1 记录的 Broker 进程。"
        return
    }

    $brokerPid = Get-Content -LiteralPath $pidFile -Raw
    if ($brokerPid -match "^\d+\s*$") {
        Stop-Process -Id ([int]$brokerPid) -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile -Force
    Write-Host "Broker 已停止。"
}

if ($StopBroker) {
    Stop-OwnedBroker
    exit 0
}

$pythonExe = Resolve-Python
$versionOk = & $pythonExe -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "需要 Python 3.11 或更高版本。当前解释器：$pythonExe"
}

if ($Setup) {
    & $pythonExe -m pip install -e $root
    if ($LASTEXITCODE -ne 0) {
        throw "项目安装失败。"
    }
}

& $pythonExe -c "import websockets"
if ($LASTEXITCODE -ne 0) {
    throw "缺少运行依赖。请先执行 .\start.ps1 -Setup。"
}

if ($CheckOnly) {
    $brokerState = if (Test-BrokerPort) { "运行中" } else { "未运行" }
    Write-Host "Python：$pythonExe"
    Write-Host "Broker：$brokerState"
    Write-Host "Extension：$extensionDir"
    exit 0
}

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
if (-not (Test-BrokerPort)) {
    $process = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList "-m", "web_llm_bridge.broker.server", "serve" `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru
    Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ascii

    $ready = $false
    foreach ($attempt in 1..30) {
        Start-Sleep -Milliseconds 100
        if (Test-BrokerPort) {
            $ready = $true
            break
        }
        if ($process.HasExited) {
            break
        }
    }
    if (-not $ready) {
        $details = if (Test-Path -LiteralPath $stderrLog) {
            Get-Content -LiteralPath $stderrLog -Raw
        } else {
            "无错误日志"
        }
        throw "Broker 启动失败：$details"
    }
    Write-Host "Broker 已启动，PID $($process.Id)。"
} else {
    Write-Host "检测到 Broker 已运行，将直接复用。"
}

Write-Host "浏览器扩展目录：$extensionDir"
Write-Host "请确认扩展已加载且 ChatGPT 已登录。"
if ($BrokerOnly) {
    exit 0
}
Write-Host ""
& $pythonExe -m web_llm_bridge.cli.interactive
exit $LASTEXITCODE
