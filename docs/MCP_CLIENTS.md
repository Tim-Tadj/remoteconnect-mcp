# MCP clients, installation and token use

Official documentation reviewed on 12 October 2026. Configuration examples have
placeholder paths; they do not install anything into a user's global settings.
Client protocol support and verified Schneider runtime behaviour are separate
claims. The [audit report](AUDIT_REPORT.md) records the verified native ST
comment-only milestone and the remaining runtime and equipment limits.

## Choose the execution host

Run the MCP process on native Windows, on the machine containing the licensed
Schneider software, COM registrations, x70 DTM catalogue and OEM XPDF context.
A client running in WSL, a Linux container or a cloud executor does not acquire
those components merely by receiving a Windows path. Point local clients at the
same dedicated virtual environment using its absolute `python.exe` path.

| Client | Local installation route | Boundary |
| --- | --- | --- |
| Codex CLI and IDE | Merge [codex.toml](../samples/codex.toml) into Codex configuration | Server must execute on the Windows engineering host |
| Claude Code | Load [claude-code.json](../samples/claude-code.json) or register a local stdio server | Native Windows execution; keep approval prompts for writes |
| Claude Desktop chat | Merge [claude_desktop_config.json](../samples/claude_desktop_config.json) into the desktop configuration | This manual configuration does not carry over to Cowork |
| Claude Cowork | Conditional local-plugin route described below | Deployment, session type and policy matter; vendor integration is unverified |
| VS Code / Copilot | Use [vscode-mcp.json](../samples/vscode-mcp.json), or the portable Claude Code sample as `.mcp.json` | Keep execution local when using a remote VS Code window |

## Install once, then launch the installed environment

For the reproducible installation verified during this audit, from the trusted
fork checkout:

```powershell
uv sync --frozen --no-dev
uv pip check --python .venv\Scripts\python.exe
```

`uv sync` uses the committed `uv.lock` instead of resolving newer dependencies.
Keep the environment installed and launch its absolute Python path in each
client. For a pip-based development installation, which resolves dependencies
within the declared ranges:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip check
```

Choose a Python version satisfying `pyproject.toml` and supported by all installed
dependencies. For a stable deployment, install a reviewed wheel or use
`pip install .` from a fixed checkout instead of an editable installation. Record
the Git commit, dependency versions, Python architecture and Schneider versions.
Avoid downloading or resolving dependencies each time a client opens a session.

`uvx` can run tools in isolated environments and accepts Git sources pinned to
commits. A reviewed alternative, after replacing `FULL_COMMIT_SHA`, is:

```powershell
uvx --from "git+https://github.com/Tim-Tadj/remoteconnect-mcp.git@FULL_COMMIT_SHA" remoteconnect-mcp
```

For this native integration the installed virtual environment is easier to
inspect and reproduce. A package fetched from Git still needs the workstation's
vendor runtimes. Do not use a bare `uvx remoteconnect-mcp` unless a reviewed
release has actually been published under that name. See [uv tool installation](https://docs.astral.sh/uv/guides/tools/).

Create a disposable project workspace, copy trusted project bundles into it,
and replace these sample settings consistently:

| Setting | Sample value and purpose |
| --- | --- |
| `command` | Absolute path to this checkout's `.venv\Scripts\python.exe` |
| `CE_MCP_XPDF_CONTEXT` | Installed `SCBForSCADAPack.xpdf`; the sample's `16.2` directory is illustrative |
| `REMOTECONNECT_HOME` | Optional native installation override; add this to `env` when the install differs from the default, for example `D:\Program Files\RemoteConnect` |
| `CE_MCP_TOOL_PROFILE` | `offline` for x70 inspection and copy editing; `inspect` for inspection; `full` for the broad legacy surface |
| `CE_MCP_ENABLE_ONLINE` | `0`; live tools require both `full` and an explicit value of `1` |
| `CE_MCP_READ_ROOTS` | Disposable working directory, such as `D:\RemoteConnect-MCP-Work` |
| `CE_MCP_WRITE_ROOTS` | Disposable working directory; keep engineering originals outside it |

Root lists use the host's path separator: `;` on Windows. These are application
checks, not an OS sandbox for vendor DLLs or COM. A local server runs with its
user account's permissions. Treat any project opened through the native vendor
runtime as trusted input, even when only inspecting a copy.
Without explicit roots, policy defaults to the process's current directory;
configure the roots instead of depending on an app's working directory. UNC and
URL paths are rejected. Read feedback with an explicit `log_path` inside the
read allowlist.

## Codex

Merge the sample TOML into `%USERPROFILE%\.codex\config.toml`, or a trusted
project's `.codex\config.toml`. Current official configuration supports tool
allow/deny lists, timeouts, approval policy and per-tool output budgets. The
sample uses `writes` approval mode and a 600-second tool timeout. Adjust the
timeout to observed native build/export durations; a client timeout does not
prove the native operation stopped. Restart the client after changing the
profile, then inspect `/mcp`. See [official OpenAI MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

The shorter CLI registration below is useful for a first connection. Merge the
sample afterwards to configure approval and timeout policy:

```powershell
codex mcp add remoteconnect --env CE_MCP_TOOL_PROFILE=inspect --env CE_MCP_ENABLE_ONLINE=0 --env CE_MCP_READ_ROOTS=D:\RemoteConnect-MCP-Work --env CE_MCP_WRITE_ROOTS=D:\RemoteConnect-MCP-Work -- "C:\path\to\remoteconnect-mcp\.venv\Scripts\python.exe" -m remoteconnect_mcp
codex mcp list
```

Add the locally installed XPDF path for logic access. A cloud continuation needs
its own confirmed local execution route; copying the TOML to a cloud container
does not make the workstation's COM broker available.

## Claude Code

For an isolated session, replace paths in the sample and run:

```powershell
claude --mcp-config .\samples\claude-code.json --strict-mcp-config
```

Alternatively register a server for this project locally:

```powershell
claude mcp add --scope local --env CE_MCP_TOOL_PROFILE=inspect CE_MCP_ENABLE_ONLINE=0 CE_MCP_READ_ROOTS=D:\RemoteConnect-MCP-Work CE_MCP_WRITE_ROOTS=D:\RemoteConnect-MCP-Work --transport stdio remoteconnect -- "C:\path\to\remoteconnect-mcp\.venv\Scripts\python.exe" -m remoteconnect_mcp
claude mcp get remoteconnect
```

Add XPDF configuration for logic access. A project-shared `.mcp.json` is another
option; review it before accepting workspace/server trust. Use `/mcp` to inspect
the connection. Tool search is enabled by default in current compatible Claude
Code deployments; keep it enabled. An optional output budget belongs to the
Claude Code process, not the server's `env`:

```powershell
$env:MAX_MCP_OUTPUT_TOKENS = "8000"
claude --mcp-config .\samples\claude-code.json --strict-mcp-config
```

Persisted or truncated results still require a bounded follow-up read. Do not
raise all output limits to compensate for returning whole projects. See
[Claude Code MCP documentation](https://code.claude.com/docs/en/mcp).

## Claude Desktop and Cowork

For Desktop chat, merge the sample into
`%APPDATA%\Claude\claude_desktop_config.json` and restart. Anthropic also supports
`.mcpb` desktop extensions, including Python and binary servers, installed via
Settings > Extensions. This repository does not ship an `.mcpb` release.
Packaging one would need a manifest, runtime/dependency strategy and vendor
prerequisite checks; it cannot bundle a Schneider licence or installation. See
[local MCP installation](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).

Cowork needs a more precise compatibility claim:

- Manual Desktop JSON servers are a separate mechanism and are unavailable in
  Cowork. See [custom connector network requirements](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).
- Anthropic documents plugin-bundled local MCP servers for Cowork and Claude
  Code. See [plugin support](https://support.claude.com/en/articles/13837440-use-plugins-in-claude).
- In documented local Cowork sessions, local plugin MCP runs natively on the
  device, while shell/code runs in a Linux VM. Local MCP does not run in cloud
  sessions. On Pro/Max, the current architecture page limits local sessions to
  tasks started on the device before 6 October 2026. Check the actual deployment
  and admin policy before promising support. See [Cowork architecture](https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview).

For an eligible local desktop session, [the plugin sample](../samples/claude-plugin/README.md)
contains `.claude-plugin/plugin.json` and a root `.mcp.json` using the same
installed Windows Python command. Replace paths and validate it before
uploading a custom plugin through Customize > Plugins. This is an installation
candidate, not proof that RemoteConnect works in the user's Cowork session. The
[plugin manifest reference](https://code.claude.com/docs/en/plugins-reference)
describes the layout. Codex or native Claude Code is the straightforward host
for this repository until Cowork's native vendor flow is tested.

Remote Claude connectors originate from Anthropic infrastructure. Turning this
stdio server into a public endpoint would require a separate authenticated
service and an explicit process-isolation design. It is not an installation
shortcut for a local engineering workstation.

## VS Code / Copilot

The existing `.vscode/mcp.json` sample remains useful for compatibility. Current
VS Code guidance prefers the portable workspace `.mcp.json` format; the Claude
Code sample has that shape. When using a remote window, confirm which host
actually launches the stdio process. See [VS Code MCP configuration](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)
and [installation guidance](https://code.visualstudio.com/docs/agent-customization/mcp-servers).

## Make useful results smaller

These are project-specific recommendations, not claims of measured token or
latency savings:

1. Start with `inspect` or `offline`. The broad generic Control Expert catalogue
   adds tools irrelevant to most x70 tasks.
2. Discover the bundle and section names once. Read one needed ST section with
   `read_st_source` and bounded `offset`/`limit`, instead of repeatedly exporting
   the whole project or graphical XML.
3. Inspect workbook schema first with `limit=0`, then select the relevant sheet
   and a small row limit. A summary or returned file path is not the full file.
   For parameter CSVs, use `inspect_parameter_csv` with `tag_filter`, bounded
   `offset`/`limit`, and an optional `dnp3_address` filename check. Use `create_parameter_csv_copy`
   with exact type/element/tag selectors and expected values for reviewed edits.
4. Stage related object/relationship edits in one copy operation, validate once,
   and build when the candidate is complete. Avoid rebuilding after each
   variable or repeatedly importing identical changes.
   `create_remoteconnect_project` requires a new parent output directory and
   publishes the paired files together; existing directories and overwrite are
   rejected. Single-file copy tools retain their explicit overwrite options.
5. Keep tool descriptions short; move rare multi-step recipes into prompts and
   language references fetched on demand. Put essential safety and workflow
   instructions at the beginning of server instructions.
6. Return counts, warnings, changed identifiers and output paths first. Preserve
   `ok`, build state, truncation markers and failure details when shortening a
   result. Never interpret omitted diagnostics as success.

MCP annotations describe tool behaviour to clients; they do not enforce
permissions. Structured output and a small output schema improve validation,
but do not inherently save tokens. Text and structured JSON can both be emitted
for compatibility. Resource links can defer large data, provided the client can
actually fetch them. See the [MCP tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).

For a meaningful comparison, record the active tool count, serialised
`tools/list` size, returned result bytes, number of tool calls and native build
time for the same disposable project under each profile. Token counts depend on
the client/model tokenizer. Keep transport, context and vendor execution costs
as separate measurements.
