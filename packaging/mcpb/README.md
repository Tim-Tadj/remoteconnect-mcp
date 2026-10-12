# RemoteConnect MCP for Claude Desktop on Windows

This MCPB includes the server, Python runtime and dependencies. You do not need
to install Python, enter a command path or edit JSON. Licensed Schneider
software must already be installed on the Windows x64 engineering workstation.
Schneider DLLs, licences and customer projects are not included.

## Install

1. Download the Windows `.mcpb` from the
   [fork's releases](https://github.com/Tim-Tadj/remoteconnect-mcp/releases).
2. Open the file with Claude Desktop, review the installation dialogue and
   install it.
3. Leave the optional workspace and XPDF settings blank for automatic setup.
   Copy complete project bundles into the dedicated workspace before using
   the server.

Claude Desktop supports installation from MCPB files on Windows and macOS,
as described in the [official MCPB overview](https://github.com/modelcontextprotocol/mcpb).
This server requires Windows x64. MCPB installation in other clients depends
on their support for the format. Use the portable Windows ZIP from the same
release for a client that accepts local STDIO servers.

## Workspace and Schneider context

The default workspace is `%LOCALAPPDATA%\RemoteConnectMCP\workspace`. The
server creates this dedicated directory when needed. To use another location,
choose a separate local directory in the extension's workspace setting.
Keep original engineering projects outside it and work with complete copies.

The server discovers the installed SCADAPack XPDF context. If discovery cannot
identify one context, select the installed `SCBForSCADAPack.xpdf` file in the
optional XPDF setting. Do not copy vendor resources into the extension.

Directory and file pickers follow the
[MCPB user configuration specification](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md#user-configuration).
The bundle uses manifest version 0.3 and launches its included executable via
`${__dirname}`, so users do not need to enter the extension's installation path.

Every launch enforces the 42-tool `offline` profile and disables online
equipment tools. Both read and write access are confined to the chosen
workspace by the server's application policy. This policy is not an operating
system sandbox. Installation and normal startup do not open a project or
connect to an RTU.

## Build validation

The release builder substitutes the version, supplies the frozen executable
and validates the staged manifest before publishing the MCPB. The
[official MCPB CLI](https://github.com/modelcontextprotocol/mcpb/blob/main/CLI.md)
provides these checks:

```powershell
mcpb validate path\to\staged\manifest.json
mcpb pack path\to\staged remoteconnect-mcp-windows-x64.mcpb
mcpb info remoteconnect-mcp-windows-x64.mcpb
```

Manifest validation checks package structure. It does not prove that a client
can install the extension or that the licensed Schneider runtime can open a
project. Runtime validation must use disposable project copies.
