[CmdletBinding()]
param([switch]$RequireClean)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = Split-Path -Parent $PSScriptRoot
$safePath = $projectRoot.Replace('\', '/')
function Invoke-Git([string[]]$Arguments) { & git -c "safe.directory=$safePath" -C $projectRoot @Arguments; if ($LASTEXITCODE -ne 0) { throw "Git 指令失敗：git $($Arguments -join ' ')" } }
Invoke-Git @('diff', '--check')
$branch = @(Invoke-Git @('branch', '--show-current'))[0]
if ([string]::IsNullOrWhiteSpace($branch)) { throw '目前為 detached HEAD；請切換至具名分支後再提交。' }
$changes = @(Invoke-Git @('status', '--short'))
Write-Output "目前分支：$branch"
if ($changes.Count -eq 0) { Write-Output '工作區乾淨。' } else { Write-Output '偵測到尚未提交的變更：'; $changes | ForEach-Object { Write-Output $_ }; if ($RequireClean) { throw 'RequireClean 已指定，但工作區仍有未提交變更。' } }
