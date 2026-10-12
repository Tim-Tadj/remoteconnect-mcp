param(
    [Parameter(Mandatory=$true)][string]$Python,
    [string]$Workspace = (Join-Path $PSScriptRoot 'workspace'),
    [string]$XpdfContext = 'C:\ProgramData\Schneider Electric\CommonControlExpert\16.2\Xpdf\SCBForSCADAPack.xpdf',
    [string]$RemoteConnectHome = ''
)
$ErrorActionPreference = 'Stop'
$bundleRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$manifest = Get-Content -LiteralPath (Join-Path $bundleRoot 'build-manifest.json') -Raw | ConvertFrom-Json
foreach ($entry in $manifest.files.PSObject.Properties) {
    $payloadPath = [IO.Path]::GetFullPath((Join-Path $bundleRoot $entry.Name))
    if (-not $payloadPath.StartsWith($bundleRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The build manifest contains a path outside the bundle.'
    }
    if ((Get-FileHash -LiteralPath $payloadPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) {
        throw "Bundle checksum mismatch: $($entry.Name)"
    }
}
& $Python -c "import os,struct,sys; assert os.name == 'nt' and sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Use CPython 3.12 for Windows x64'"
if ($LASTEXITCODE -ne 0) { throw 'A Windows x64 CPython 3.12 interpreter is required.' }
$runtime = Join-Path $bundleRoot '.runtime'
if (-not (Test-Path -LiteralPath $runtime)) {
    & $Python -m venv $runtime
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the local Python runtime.' }
}
$runtimePython = Join-Path $runtime 'Scripts\python.exe'
& $runtimePython -c "import os,struct,sys; assert os.name == 'nt' and sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8"
if ($LASTEXITCODE -ne 0) { throw 'Existing .runtime uses an incompatible Python interpreter.' }
& $runtimePython -m pip install --no-index --only-binary=:all: --require-hashes --disable-pip-version-check --find-links (Join-Path $bundleRoot 'wheelhouse') --requirement (Join-Path $bundleRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Offline package installation failed.' }
& $runtimePython -m pip check --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw 'Installed package dependencies are incompatible.' }
$configureArguments = @((Join-Path $bundleRoot 'configure.py'), '--workspace', $Workspace, '--xpdf-context', $XpdfContext)
if ($RemoteConnectHome) { $configureArguments += @('--remoteconnect-home', $RemoteConnectHome) }
& $runtimePython @configureArguments
if ($LASTEXITCODE -ne 0) { throw 'Client configuration failed.' }
Write-Host 'Setup complete. Run the Start script in this directory.'
