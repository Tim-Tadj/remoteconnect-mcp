# RemoteConnect MCP for the ChatGPT desktop app

1. Extract this ZIP to a permanent local folder on your Windows engineering workstation.
2. Double-click `Install-ChatGPT.cmd`.
3. Review the plugin in ChatGPT and select **Install**. Start a new local chat.

Python and the server dependencies are included. Setup checks the payload
hashes, detects a single installed SCADAPack XPDF context and creates an empty
`workspace` folder. Copy trusted project bundles into it. Keep engineering
originals elsewhere. Licensed Schneider software is installed separately.

The server enforces the 42-tool offline profile and disabled online operations.
Workspace boundaries are application checks, not an OS sandbox for vendor code.

For a different disposable folder or an ambiguous Schneider installation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-ChatGPT.ps1 -Workspace 'D:\RemoteConnect-MCP-Work' -XpdfContext 'C:\Path\To\SCBForSCADAPack.xpdf'
```

The installer opens the documented local plugin review link. You approve the
installation in the app. It does not overwrite global client settings. Keep
this extracted folder in place because the installed plugin refers to its
runtime. Rerun the installer after moving it and reinstall the refreshed plugin.

For the custom MCP form, the command is the absolute path to
`runtime\remoteconnect-mcp.exe`. Leave arguments, environment fields and working
directory blank to use `%LOCALAPPDATA%\RemoteConnectMCP\workspace`. That direct
form uses this separate default folder. Use the plugin installer to use the
bundle's `workspace` folder, and avoid registering the server twice.

The ZIP targets local Windows execution in the ChatGPT desktop app. ChatGPT web
and cloud execution do not gain access to this workstation's Schneider runtime.
These builds are unsigned, so Windows or workplace policy may prompt or block them.

The local install route follows [official OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins)
and the [desktop plugin link reference](https://learn.chatgpt.com/docs/app/commands).
MCPB is provided separately for clients that support it, including Claude Desktop.
