$ErrorActionPreference = 'Stop'
$pluginPath = Join-Path $PSScriptRoot 'claude-plugin'
if (-not (Test-Path -LiteralPath (Join-Path $pluginPath '.mcp.json'))) { throw 'Run Setup.ps1 first.' }
$configuration = Get-Content -LiteralPath (Join-Path $pluginPath '.mcp.json') -Raw | ConvertFrom-Json
Push-Location -LiteralPath $configuration.mcpServers.remoteconnect.env.CE_MCP_READ_ROOTS
try {
    & claude --plugin-dir $pluginPath @args
    $clientExitCode = $LASTEXITCODE
} finally { Pop-Location }
exit $clientExitCode
