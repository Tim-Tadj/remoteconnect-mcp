# Windows client builds

Release assets contain a server wheel, pinned Windows dependency wheels and a
client-specific plugin/configuration. They target **CPython 3.12 x64 on Windows**.
Python, Codex/Claude Code, licensed Schneider software and the SCADAPack XPDF
context must already be installed. Vendor DLLs, licences and customer projects
are not redistributed.

## Install a downloaded bundle

Extract the Codex or Claude Code ZIP into a permanent local directory. In that
directory, run this with your installed CPython 3.12 interpreter:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1 -Python 'C:\Python312\python.exe'
```

The execution policy applies only to that PowerShell process. Setup checks the
payload hashes, creates `.runtime`, installs the pinned wheels without network
access and writes local client configuration. It does not modify global client
settings. The default disposable project directory is `workspace` beside Setup.

For a different installed context or disposable workspace:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1 -Python 'C:\Python312\python.exe' -Workspace 'D:\RemoteConnect-MCP-Work' -XpdfContext 'C:\ProgramData\Schneider Electric\CommonControlExpert\16.2\Xpdf\SCBForSCADAPack.xpdf' -RemoteConnectHome 'D:\Program Files\RemoteConnect'
```

Use a separate working directory, and copy trusted PRJ/STU project files into
it. Both clients start in that directory. Online operations remain disabled.

Launch the chosen client with `Start-Codex.ps1` or `Start-ClaudeCode.ps1`.
The Codex launcher requires PowerShell 7.3 or later so quoted configuration
arguments reach the CLI intact:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\Start-Codex.ps1
# For the Claude Code bundle:
powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-ClaudeCode.ps1
```
The Codex launcher uses per-session MCP configuration. The Claude launcher
loads `claude-plugin` with `--plugin-dir`. The bundles also contain local
marketplace metadata for optional plugin installation, described in their
READMEs. Avoid loading the same server twice in one client session.

After moving an extracted bundle, rerun Setup to update its absolute runtime
and project paths. Keep the extracted directory when using a cached plugin,
because its MCP command points to that directory's runtime.

## Build from source

Use a clean committed checkout of the fork and the locked development runtime:

```powershell
uv sync --frozen --no-dev --python 3.12
.\.venv\Scripts\python.exe -m ensurepip
.\.venv\Scripts\python.exe tools\build_client_bundles.py
```

The build needs `uv`, `git`, pip and package-index access for the dependency
download. It records the source commit, checks the server wheel's contents and
produces two ZIPs, the shared wheel and `SHA256SUMS.txt` under `dist/<version>`.
It refuses an existing release directory rather than replacing released files.
Dependencies install offline from the finished bundle; creating the bundle
may download the pinned dependency wheels.

Plugin layouts follow [official OpenAI packaging documentation](https://developers.openai.com/plugins/build/plugins)
and the [Claude Code manifest reference](https://code.claude.com/docs/en/plugins-reference).
Local stdio execution requires the Windows engineering host. A cloud executor
does not gain access to the workstation's COM registrations from this ZIP.
