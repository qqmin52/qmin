# Windows 一键安装：创建 .venv、安装依赖、可选构建面板、自动初始化配置。
# 幂等，可重复执行；任何一步失败立即停止并打印失败的命令。
[CmdletBinding()]
param(
    [switch]$BuildPanel
)

# 用 Continue：PowerShell 5.1 会把原生命令的 stderr（pip / npm 的正常警告）当成错误记录，
# 若设为 Stop 会在命令成功时误中止；外部命令的失败统一由 $LASTEXITCODE 显式判断。
$ErrorActionPreference = 'Continue'

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repoRoot

function Fail {
    param([string]$Message)
    Write-Host "[失败] $Message" -ForegroundColor Red
    exit 1
}

function Step {
    param([string]$Message)
    Write-Host "==> $Message"
}

# 1. 定位 Python 3.11+
$pythonExe = $null
$pythonArgs = @()
foreach ($candidate in @(@{ Exe = 'python'; Args = @() }, @{ Exe = 'py'; Args = @('-3') })) {
    if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) {
        continue
    }
    $versionText = $null
    $probeExit = 1
    $probeErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $versionText = & $candidate.Exe @($candidate.Args + @('-c', 'import sys; print(sys.version_info.major * 100 + sys.version_info.minor)')) 2>$null
        $probeExit = $LASTEXITCODE
    } catch {
        $versionText = $null
        $probeExit = 1
    } finally {
        $ErrorActionPreference = $probeErrorAction
    }
    if ($probeExit -ne 0 -or -not $versionText) {
        continue
    }
    $versionCode = 0
    try {
        $versionCode = [int]"$versionText".Trim()
    } catch {
        continue
    }
    if ($versionCode -ge 311) {
        $pythonExe = $candidate.Exe
        $pythonArgs = $candidate.Args
        break
    }
}

if (-not $pythonExe) {
    Write-Host "未找到 Python 3.11+，请先安装：https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

# 2. 创建 / 复用 .venv
$venvDir = Join-Path $repoRoot '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Step "创建虚拟环境 .venv"
    & $pythonExe @($pythonArgs + @('-m', 'venv', '.venv'))
    if ($LASTEXITCODE -ne 0) {
        Fail "命令失败：$pythonExe $($pythonArgs -join ' ') -m venv .venv"
    }
} else {
    Step "复用已存在的虚拟环境 .venv"
}

# 3. 安装依赖
Step "升级 pip"
& $venvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) {
    Fail "命令失败：$venvPython -m pip install --upgrade pip"
}

Step "安装项目依赖（pip install -e .）"
& $venvPython -m pip install -e .
if ($LASTEXITCODE -ne 0) {
    Fail "命令失败：$venvPython -m pip install -e ."
}

# 4. 面板构建（可选）
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
$npmAvailable = $false
if ($npm) {
    & npm.cmd --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $npmAvailable = $true
    }
}

if ($BuildPanel) {
    if (-not $npmAvailable) {
        Fail "指定了 -BuildPanel，但未找到可用的 npm.cmd，请先安装 Node.js 18+：https://nodejs.org/"
    }
    $shouldBuild = $true
} elseif ($npmAvailable) {
    $shouldBuild = $true
} else {
    Write-Host "未检测到 Node.js，跳过面板构建（机器人功能不受影响）" -ForegroundColor Yellow
    $shouldBuild = $false
}

if ($shouldBuild) {
    $webuiDir = Join-Path $repoRoot 'webui'
    Step "安装前端依赖（npm.cmd install）"
    Push-Location $webuiDir
    try {
        & npm.cmd install
        if ($LASTEXITCODE -ne 0) {
            Fail "命令失败：npm.cmd install（目录：webui）"
        }
        Step "构建前端（npm.cmd run build）"
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) {
            Fail "命令失败：npm.cmd run build（目录：webui）"
        }
    } finally {
        Pop-Location
    }
}

# 5. 初始化配置
$envFile = Join-Path $repoRoot '.env'
$qminExe = Join-Path $venvDir 'Scripts\qmin.exe'
if (-not (Test-Path $envFile)) {
    Step "初始化配置（qmin init）"
    & $qminExe init
    if ($LASTEXITCODE -ne 0) {
        Fail "命令失败：$qminExe init"
    }
} else {
    Write-Host "检测到已存在 .env，跳过初始化（如需重新配置请先删除 .env）" -ForegroundColor Yellow
}

# 6. 完成提示
Write-Host ""
Write-Host "安装完成，下一步：" -ForegroundColor Green
Write-Host "  1. 检查配置：.\\.venv\\Scripts\\qmin.exe doctor"
Write-Host "  2. 启动：    .\\.venv\\Scripts\\qmin.exe start"
Write-Host "  3. 管理面板：http://127.0.0.1:8000"
Write-Host "     令牌：在另一个终端执行 .\\.venv\\Scripts\\qmin.exe token 复制到剪贴板"
