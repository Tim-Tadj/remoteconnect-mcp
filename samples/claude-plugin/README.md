# Local Claude plugin sample

This sample connects to an already installed Windows virtual environment. It
does not include Python, vendor DLLs, a Schneider licence or an `.mcpb` bundle.

1. Follow [MCP installation](../../docs/MCP_CLIENTS.md) and prepare a disposable
   project workspace on the engineering workstation.
2. Copy this sample directory to a local configuration directory, then replace
   the Python, workspace and XPDF paths in `.mcp.json`.
   Add `REMOTECONNECT_HOME` to its `env` object for a non-default native install.
3. Validate the copied directory:

```powershell
claude plugin validate "C:\path\to\configured-remoteconnect-plugin"
```

For a Claude Code test session:

```powershell
claude --plugin-dir "C:\path\to\configured-remoteconnect-plugin"
```

Use `/mcp` to confirm connection and the expected offline tool catalogue. Do not
also configure the same server manually in that session.

For an eligible local Cowork desktop deployment, archive the **contents** of the
configured plugin directory, preserving `.claude-plugin/plugin.json` and
`.mcp.json`, then upload the custom plugin through Customize > Plugins. Current
Cowork cloud sessions do not run local MCP servers; see the version and session
limits in [MCP client guidance](../../docs/MCP_CLIENTS.md). This is a local-plugin
installation sample with unverified RemoteConnect runtime compatibility.

The sample starts with `offline`, restricts explicit reads/writes to the
disposable directory and disables online tools. Set `inspect` for an inspection
session. Verify the actual manifest version against the installed server when
packaging a release.

Configuration format: [Anthropic plugin manifest reference](https://code.claude.com/docs/en/plugins-reference).
