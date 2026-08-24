[CmdletBinding()]
param([string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $candidates = @((Join-Path $projectRoot '.venv\Scripts\python.exe'), (Join-Path $projectRoot 'python_embed\python.exe'))
    $PythonPath = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $PythonPath) { $command = Get-Command python -ErrorAction SilentlyContinue; if ($command) { $PythonPath = $command.Source } }
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw '找不到 Python。請建立 .venv、保留 python_embed，或以 -PythonPath 指定 python.exe。' }
Push-Location $projectRoot
try { & $PythonPath -m unittest discover -s tests -v; if ($LASTEXITCODE -ne 0) { throw "單元測試失敗（exit code: $LASTEXITCODE）。" } } finally { Pop-Location }
