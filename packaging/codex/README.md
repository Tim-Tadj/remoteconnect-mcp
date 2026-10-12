# RemoteConnect MCP for Codex

Windows x64 prerelease bundle for native Codex sessions. It contains the server
executable, Python runtime, locked dependencies and an offline profile. Schneider software and
customer projects are installed separately.

Extract the ZIP to a permanent directory on the engineering workstation. In
PowerShell 7.3 or later (`pwsh`), from that directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\Start-Codex.ps1
```

Python is included. Setup checks the bundled runtime and writes absolute local
launch paths without downloading packages. Optional setup arguments are
`-Workspace`, `-XpdfContext` and `-RemoteConnectHome`. The default workspace is
the bundle's `workspace` directory. Place disposable project copies there.
The generated configuration uses `CE_MCP_TOOL_PROFILE=offline` and
`CE_MCP_ENABLE_ONLINE=0`.

For the ChatGPT desktop app, double-click `Install-ChatGPT.cmd`, then review
and install the plugin in the app. No custom MCP form fields are required.

`Start-Codex.ps1` requires PowerShell 7.3 or later to preserve quoted CLI
arguments, and passes the generated MCP settings to one Codex session. Setup
and the launcher do not edit global Codex settings. Inspect `/mcp` in the new
session to check the connection. Native logic tools still require the licensed
RemoteConnect installation and its XPDF context on this Windows host.

The optional plugin uses OpenAI's supported Codex compatibility layout. After
setup, register this bundle as a local marketplace:

```powershell
codex plugin marketplace add 'C:\path\to\extracted-bundle'
codex plugin add remoteconnect-mcp@remoteconnect-local
codex plugin list
```

These registration commands persist plugin settings. Open a new Codex session
after installation. Use either the plugin or the session launcher for a session
to avoid starting the same server twice. The plugin's generated command points
at the installed runtime in the extracted bundle, even when Codex caches its
plugin files. Keep the bundle in place; after moving it, rerun setup and refresh
the installed plugin.

Inspect the generated `codex.toml` for the direct MCP fallback. Keep approval
prompts for writes and use bounded section or parameter reads. The workspace
allowlists are application checks, so the server still runs with the Windows
account's permissions. Do not place engineering originals in that workspace or
use this offline build to operate an RTU.

Packaging does not establish native vendor or manual GUI compatibility. See
the [audit report](https://github.com/Tim-Tadj/remoteconnect-mcp/blob/main/docs/AUDIT_REPORT.md)
for the separate validation results and
[client guidance](https://github.com/Tim-Tadj/remoteconnect-mcp/blob/main/docs/MCP_CLIENTS.md)
for installation prerequisites.

Manifest and local marketplace layout follow the
[official OpenAI packaging documentation](https://developers.openai.com/plugins/build/plugins).
The installed Codex CLI exposes `plugin add`, `list`, `remove` and marketplace
management. It has no `plugin validate` command; check the generated JSON,
declared asset paths and stdio handshake before distribution.
