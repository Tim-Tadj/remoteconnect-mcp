"""Configure the unpacked client bundle without modifying global settings."""

import argparse
import json
from importlib.metadata import version
from pathlib import Path


def configure(root, workspace=None, xpdf_context=None, remoteconnect_home=""):
    root = Path(root).resolve()
    manifest = json.loads((root / "build-manifest.json").read_text(encoding="utf-8"))
    if version("remoteconnect-mcp") != manifest["version"]:
        raise ValueError("Installed server version does not match this bundle")
    client = manifest["client"]
    if client not in {"codex", "chatgpt", "claude-code"}:
        raise ValueError("Unknown bundle client")
    workspace = workspace or root / "workspace"
    if str(workspace).startswith(("\\\\", "//")) or any(value in str(workspace) for value in ("://", ";", "${")) or ":" in str(workspace)[2:]:
        raise ValueError("Workspace must be a local directory without a semicolon")
    workspace = Path(workspace).expanduser().resolve()
    if root.is_relative_to(workspace) or (workspace.is_relative_to(root) and not workspace.is_relative_to(root / "workspace")):
        raise ValueError("Use a separate disposable project workspace")
    if not xpdf_context:
        from server_launcher import discover_xpdf
        xpdf_context = discover_xpdf()
    if not xpdf_context or not Path(xpdf_context).is_file():
        raise ValueError("Supply the installed SCADAPack XPDF file using -XpdfContext")
    xpdf = Path(xpdf_context).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    environment = {
        "CE_MCP_TOOL_PROFILE": "offline", "CE_MCP_ENABLE_ONLINE": "0",
        "CE_MCP_WORKSPACE": str(workspace),
        "CE_MCP_READ_ROOTS": str(workspace), "CE_MCP_WRITE_ROOTS": str(workspace),
        "CE_MCP_XPDF_CONTEXT": str(xpdf),
    }
    if remoteconnect_home:
        environment["REMOTECONNECT_HOME"] = str(Path(remoteconnect_home).resolve())
    plugin = root / ("codex-plugin" if client in {"codex", "chatgpt"} else "claude-plugin")
    server = {"type": "stdio", "command": str(root / "runtime" / "remoteconnect-mcp.exe"),
              "args": [], "env": environment}
    (plugin / ".mcp.json").write_text(json.dumps({"mcpServers": {"remoteconnect": server}}, indent=2), encoding="utf-8")
    if client in {"codex", "chatgpt"}:
        settings = {key: value for key, value in server.items() if key != "type"}
        settings.update(startup_timeout_sec=30, tool_timeout_sec=600, default_tools_approval_mode="writes")
        arguments = ["-C", str(workspace)]
        lines = ["[mcp_servers.remoteconnect]"]
        for key, value in settings.items():
            if key == "env":
                continue
            lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
            arguments.extend(["-c", f"mcp_servers.remoteconnect.{key}={json.dumps(value, ensure_ascii=False)}"])
        lines.append("\n[mcp_servers.remoteconnect.env]")
        for key, value in environment.items():
            lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
            arguments.extend(["-c", f"mcp_servers.remoteconnect.env.{key}={json.dumps(value, ensure_ascii=False)}"])
        (root / "codex.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (root / "codex-args.json").write_text(json.dumps(arguments), encoding="utf-8")
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--xpdf-context", required=True)
    parser.add_argument("--remoteconnect-home", default="")
    args = parser.parse_args()
    configure(Path(__file__).parent, args.workspace, args.xpdf_context, args.remoteconnect_home)
