param(
    [string]$Workspace = '',
    [string]$XpdfContext = '',
    [string]$RemoteConnectHome = ''
)
$ErrorActionPreference = 'Stop'
$bundleRoot = [IO.Path]::GetFullPath($PSScriptRoot)
if (-not $Workspace) { $Workspace = Join-Path $bundleRoot 'workspace' }
$manifest = Get-Content -LiteralPath (Join-Path $bundleRoot 'build-manifest.json') -Raw | ConvertFrom-Json
foreach ($entry in $manifest.files.PSObject.Properties) {
    $payloadPath = [IO.Path]::GetFullPath((Join-Path $bundleRoot $entry.Name))
    if (-not $payloadPath.StartsWith($bundleRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The build manifest contains a path outside the bundle.'
    }
    $payloadStream = [IO.File]::OpenRead($payloadPath)
    $hashAlgorithm = [Security.Cryptography.SHA256]::Create()
    try { $payloadHash = [BitConverter]::ToString($hashAlgorithm.ComputeHash($payloadStream)).Replace('-', '').ToLowerInvariant() }
    finally { $payloadStream.Dispose(); $hashAlgorithm.Dispose() }
    if ($payloadHash -ne $entry.Value) {
        throw "Bundle checksum mismatch: $($entry.Name)"
    }
}
$serverExecutable = Join-Path $bundleRoot 'runtime\remoteconnect-mcp.exe'
& $serverExecutable --self-check
if ($LASTEXITCODE -ne 0) { throw 'The bundled runtime check failed.' }
$configureArguments = @('--configure-bundle', $bundleRoot, '--workspace', $Workspace)
if ($XpdfContext) { $configureArguments += @('--xpdf-context', $XpdfContext) }
if ($RemoteConnectHome) { $configureArguments += @('--remoteconnect-home', $RemoteConnectHome) }
& $serverExecutable @configureArguments
if ($LASTEXITCODE -ne 0) { throw 'Client configuration failed.' }
Write-Host 'Setup complete. Run the Start script in this directory.'
