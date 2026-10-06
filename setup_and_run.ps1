[CmdletBinding(PositionalBinding = $false)]
param(
    [switch]$NoLaunch,
    [switch]$CheckOnly,
    [switch]$Force,
    [string]$PythonPath = '',
    [string]$TargetProject = '',
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$AppArguments = @()
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
# 開發環境與發布用 embedded runtime 各自維護；不覆寫既有環境。
$projectDir = $PSScriptRoot
$pythonExe = Join-Path $projectDir '.venv\Scripts\python.exe'
$requirements = Join-Path $projectDir 'requirements.txt'
$entryPoint = 'main.py'
$imports = 'tkinter,sqlite3,webview,PIL,pillow_heif,geopy,pystray,cv2,numpy'
$probe = @'
import sys, importlib, importlib.metadata, pathlib
assert sys.version_info[:2] == (3, 13), '專案環境必須使用 Python 3.13'
assert sys.prefix != sys.base_prefix, '必須使用專案虛擬環境'
for name in sys.argv[2].split(','): importlib.import_module(name)
for line in pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line and not line.startswith('#'):
        name, version = line.split('==')
        assert importlib.metadata.version(name) == version, f'{name} 版本不符：需要 {version}'
print('READY', sys.version.split()[0], sys.executable)
'@
function Test-ProjectEnvironment {
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) { return $false }
    $probeOutput = @(& $pythonExe -B -s -c $probe $requirements $imports 2>&1)
    foreach ($line in $probeOutput) { Write-Host $line }
    return ($LASTEXITCODE -eq 0)
}
if ($CheckOnly) {
    if (-not (Test-ProjectEnvironment)) { throw '專案 .venv 尚未就緒；請執行 setup_and_run.ps1 -NoLaunch。檢查模式不會建立或安裝環境。' }
    & $pythonExe -B -s -m pip --disable-pip-version-check check
    if ($LASTEXITCODE -ne 0) { throw '專案套件相依檢查失敗。' }
    return
}
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    if (Test-Path -LiteralPath (Join-Path $projectDir '.venv')) { throw '既有 .venv 不完整；保留現場，請先檢查，不會自動刪除。' }
    if ([string]::IsNullOrWhiteSpace($PythonPath)) {
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($launcher) { $PythonPath = & $launcher.Source -3.13 -B -c 'import sys; print(sys.executable)' }
        if (-not $PythonPath) {
            $candidate = Get-Command python.exe -ErrorAction SilentlyContinue
            if ($candidate) { $PythonPath = $candidate.Source }
        }
    }
    if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw '請安裝完整 Python 3.13（含 Tcl/Tk），或以 -PythonPath 指定。' }
    & $PythonPath -B -s -c 'import sys, tkinter; assert sys.version_info[:2] == (3,13)'
    if ($LASTEXITCODE -ne 0) { throw '來源必須是完整 Python 3.13；不會改用其他版本。' }
    & $PythonPath -B -s -m venv (Join-Path $projectDir '.venv')
    if ($LASTEXITCODE -ne 0) { throw '建立 .venv 失敗。' }
}
& $pythonExe -B -s -c 'import sys; assert sys.version_info[:2] == (3,13) and sys.prefix != sys.base_prefix'
if ($LASTEXITCODE -ne 0) { throw '既有環境版本不符；保留環境，不會重建或改用全域 Python。' }
if ($Force -or -not (Test-ProjectEnvironment)) {
    # -Force 僅重新套用宣告套件，不刪除虛擬環境或 embedded runtime。
    & $pythonExe -B -s -m pip --disable-pip-version-check install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw '安裝失敗；環境保留，請檢查網路及套件錯誤。' }
    if (-not (Test-ProjectEnvironment)) { throw '安裝後環境驗證失敗。' }
    & $pythonExe -B -s -m pip --disable-pip-version-check check
    if ($LASTEXITCODE -ne 0) { throw '安裝後套件相依檢查失敗。' }
}
if ($NoLaunch) { return }
Push-Location $projectDir
try {
    & $pythonExe -B -s (Join-Path $projectDir $entryPoint) @AppArguments
    if ($LASTEXITCODE -ne 0) { throw "程式結束碼：$LASTEXITCODE" }
} finally { Pop-Location }
