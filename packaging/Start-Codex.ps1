#Requires -Version 7.3
$ErrorActionPreference = 'Stop'
$PSNativeCommandArgumentPassing = 'Standard'
$argumentFile = Join-Path $PSScriptRoot 'codex-args.json'
if (-not (Test-Path -LiteralPath $argumentFile)) { throw 'Run Setup.ps1 first.' }
$clientArguments = @(Get-Content -LiteralPath $argumentFile -Raw | ConvertFrom-Json)
& codex @clientArguments @args
exit $LASTEXITCODE
