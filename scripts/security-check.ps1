[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = Split-Path -Parent $PSScriptRoot
$safePath = $projectRoot.Replace('\', '/')
$tracked = @(& git -c "safe.directory=$safePath" -C $projectRoot ls-files --cached --others --exclude-standard)
if ($LASTEXITCODE -ne 0) { throw '無法讀取 Git 追蹤檔案清單。' }
$pattern = '(?i)(api[_-]?key|secret|access[_-]?token|password)\s*[:=]\s*["''][^"'']{8,}'
$findings = @()
foreach ($relative in $tracked) {
    if ($relative -match '(^|/)\.env(\.|$)' -or $relative -match '\.(png|jpe?g|gif|zip|db|ico)$') { continue }
    $path = Join-Path $projectRoot $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
    try { $matches = Select-String -LiteralPath $path -Pattern $pattern -AllMatches -Encoding UTF8 -ErrorAction Stop; foreach ($match in $matches) { $findings += "${relative}:$($match.LineNumber)" } } catch [System.ArgumentException] { continue }
}
if ($findings.Count -gt 0) { $findings | ForEach-Object { Write-Error "疑似敏感值：$_" }; throw '敏感字串檢查失敗；請確認不是 API Key、密碼或 Token 後再提交。' }
Write-Output '未發現已追蹤文字檔中的明顯敏感值。'
