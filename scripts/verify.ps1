#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Federation Verification Engine — thin PowerShell wrapper for verify.py.
.DESCRIPTION
    Resolves verify.py from this script's location, forwards all arguments,
    and propagates the child process exit code.
    No verification logic. No dependency installation. No service access.
    Exit codes match verify.py: 0=pass, 1=fail, 2=usage, 3=internal.
#>
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $ForwardedArgs
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $PSCommandPath
$verifyPy = Join-Path $scriptRoot 'verify.py'

if (-not (Test-Path -LiteralPath $verifyPy)) {
    Write-Error "verify.py not found at $verifyPy"
    exit 3
}

$python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $python) {
    $python = (Get-Command python3 -ErrorAction SilentlyContinue)
}
if (-not $python) {
    Write-Error "Python not found in PATH"
    exit 3
}

# Use ConsoleHost to ensure child exit code propagates cleanly
$allArgs = @($verifyPy) + $ForwardedArgs
$proc = Start-Process -FilePath $python.Source -ArgumentList $allArgs -NoNewWindow -PassThru -Wait
exit $proc.ExitCode
