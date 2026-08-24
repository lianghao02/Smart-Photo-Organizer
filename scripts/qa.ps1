[CmdletBinding()]
param([string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
& (Join-Path $PSScriptRoot 'test.ps1') -PythonPath $PythonPath
& (Join-Path $PSScriptRoot 'security-check.ps1')
& (Join-Path $PSScriptRoot 'git-verify.ps1')
Write-Output 'QA 完成。'
