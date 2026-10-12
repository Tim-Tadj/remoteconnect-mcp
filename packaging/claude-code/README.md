# RemoteConnect MCP for Claude Code on Windows

Extract this ZIP to a permanent directory on the Windows engineering workstation.
It contains the MCP executable, Python runtime, pinned dependencies and local scripts.
It starts with the 42-tool `offline` profile and disables online equipment tools.

You need Windows x64, Claude Code installed on Windows and the licensed
Schneider software required by your project. Python is included; vendor DLLs,
licences and customer projects are installed separately.

## Set up and start

Open PowerShell in the extracted directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-ClaudeCode.ps1
```

Setup checks the bundle's file hashes and included runtime without downloading
dependencies. It generates the plugin's
`.mcp.json` with absolute paths. It does not register anything in Claude settings.
The launcher opens Claude Code in the configured workspace and loads the local
plugin using `--plugin-dir`.

The default workspace is the empty `workspace` directory beside these scripts.
Copy complete project bundles into it for inspection and editing. Keep engineering
originals outside it. To use another disposable workspace or Schneider context,
run setup with the appropriate paths:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1 -Workspace "D:\RemoteConnect-MCP-Work" -XpdfContext "C:\Path\To\SCBForSCADAPack.xpdf"
```

Setup discovers a single installed SCADAPack XPDF context automatically.
Use `-RemoteConnectHome "C:\Path\To\RemoteConnect"` for a non-default vendor
installation. Re-run setup after moving the extracted directory or changing
these paths. The workspace allowlists are application checks, not an OS sandbox.

Validate the configured plugin, then use `/mcp` in Claude Code to check its
connection and tool catalogue:

```powershell
claude plugin validate --strict .\claude-plugin
```

Plugin validation and the launcher follow the
[Anthropic plugin manifest reference](https://code.claude.com/docs/en/plugins-reference).
Validation does not prove that the installed Schneider runtime can open a project.
Use bounded reads and narrow parameter selectors to keep results small. Preserve
build failures, warnings and truncation details when summarising tool output.

## Optional persistent project installation

For regular use, run these commands from the disposable project directory where
you want Claude Code to remember the plugin. Replace the bundle path:

```powershell
claude plugin marketplace add --scope local "D:\Tools\RemoteConnect-ClaudeCode"
claude plugin install --scope local remoteconnect-mcp@remoteconnect-local
```

This explicitly records a local marketplace and plugin installation for that
project. Keep the extracted bundle in place. Start `claude` normally afterwards,
without also loading `--plugin-dir` or registering a second copy of the server.
The marketplace route follows
[Anthropic's local marketplace documentation](https://code.claude.com/docs/en/plugin-marketplaces).

This build targets native Windows Claude Code. Schneider runtime validation uses
disposable copies. Physical RTU operations are outside this workflow.
