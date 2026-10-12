# Easy Windows installation

Portable releases target Windows x64 and include CPython 3.12, the server and
locked dependencies. No Python installation, pip commands or dependency downloads
are needed. Licensed Schneider software and customer projects are installed
separately. These builds are unsigned.

## ChatGPT desktop app

1. Download and extract the ChatGPT ZIP into a permanent local folder.
2. Double-click `Install-ChatGPT.cmd`.
3. Review RemoteConnect MCP in ChatGPT and select **Install**. Start a new local chat.

Setup verifies the payload hashes and included runtime, discovers a single
installed SCADAPack XPDF context, and creates an empty `workspace` folder.
Copy trusted project bundles into it. Keep engineering originals elsewhere.
The installer opens the app's plugin review page; it does not edit global client
configuration or approve installation on the user's behalf.

For a different disposable folder or several installed Schneider contexts:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-ChatGPT.ps1 -Workspace 'D:\RemoteConnect-MCP-Work' -XpdfContext 'C:\Path\To\SCBForSCADAPack.xpdf'
```

This follows [OpenAI's desktop plugin link](https://learn.chatgpt.com/docs/app/commands)
and [local plugin packaging](https://developers.openai.com/plugins/build/plugins).
ChatGPT desktop and Codex share local MCP configuration. This package uses
Windows local execution; ChatGPT web/cloud does not acquire the workstation's
Schneider runtime. See [OpenAI's MCP host documentation](https://learn.chatgpt.com/docs/extend/mcp).

Keep the extracted folder in place because the cached plugin's MCP command
refers to its runtime. After moving it, rerun installation and refresh the plugin.
Avoid registering the same server twice.

## Claude Desktop MCPB

Open the `.mcpb` file with Claude Desktop and review the installation. The Python
runtime is inside the bundle. Optional workspace and XPDF pickers support custom
paths; blank values use `%LOCALAPPDATA%\RemoteConnectMCP\workspace` and discover
the installed context. Copy trusted project bundles into that workspace.

MCPB is a ZIP plus a manifest supported by Claude Desktop. OpenAI documentation
does not establish a ChatGPT MCPB importer, so use the ChatGPT ZIP for that app.
See the [official MCPB repository](https://github.com/modelcontextprotocol/mcpb)
and [manifest specification](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md).

## Codex and Claude Code

Extract the appropriate ZIP, then run Setup and the chosen launcher:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1
# Codex, using PowerShell 7.3 or later:
pwsh -NoProfile -ExecutionPolicy Bypass -File .\Start-Codex.ps1
# Claude Code:
powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-ClaudeCode.ps1
```

The execution policy applies only to that process. Codex's launcher uses
per-session configuration and requires modern argument preservation. Claude
Code uses `--plugin-dir`. The READMEs describe optional permanent registrations.
Setup accepts `-Workspace`, `-XpdfContext` and `-RemoteConnectHome`.

## Custom MCP form fallback

In the form shown by the ChatGPT desktop app, set **Name** to `remoteconnect`
and **Command to launch** to the extracted `runtime\remoteconnect-mcp.exe`'s
absolute path. Leave arguments, environment fields and working directory blank.
The server then uses `%LOCALAPPDATA%\RemoteConnectMCP\workspace`.

All portable launches enforce the 42-tool offline profile, disabled online
operations and a single disposable read/write workspace. These application
checks are not an OS sandbox for vendor assemblies. A portable install does not
establish native configuration import, manual GUI or physical equipment behaviour.

## Build from source

Use a clean committed fork checkout on Windows:

```powershell
uv sync --frozen --group build --python 3.12
.\.venv\Scripts\python.exe tools\build_client_bundles.py
```

The build needs `uv`, `git`, Windows x64 CPython 3.12 and package-index access
to create the locked build environment. PyInstaller is a build-only dependency.
The builder records the commit, checks the server wheel and portable runtime,
preserves Python/dependency licences and produces three ZIPs, one MCPB, the
shared wheel and `SHA256SUMS.txt` under `dist/<version>`. It refuses existing output.
The finished packages launch without dependency downloads. The standalone wheel
remains available for source-style deployments using an installed Python runtime.
