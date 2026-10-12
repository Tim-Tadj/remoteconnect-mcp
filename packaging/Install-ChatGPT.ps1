param(
    [string]$Workspace = '',
    [string]$XpdfContext = '',
    [switch]$PrintLink
)
$ErrorActionPreference = 'Stop'
try {
    $setupArguments = @{}
    if ($Workspace) { $setupArguments.Workspace = $Workspace }
    if ($XpdfContext) { $setupArguments.XpdfContext = $XpdfContext }
    & (Join-Path $PSScriptRoot 'Setup.ps1') @setupArguments
    $marketplacePath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '.claude-plugin\marketplace.json'))
    if (-not (Test-Path -LiteralPath $marketplacePath -PathType Leaf)) {
        throw 'The ChatGPT plugin marketplace is missing from this bundle.'
    }
    $pluginLink = 'codex://plugins/remoteconnect-mcp?marketplacePath=' + [Uri]::EscapeDataString($marketplacePath)
    if ($PrintLink) { Write-Output $pluginLink }
    else {
        Start-Process $pluginLink
        Write-Host 'Review RemoteConnect MCP in ChatGPT, then select Install.'
    }
}
catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
