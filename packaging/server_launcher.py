"""Portable Windows entrypoint with a fixed offline project boundary."""

import argparse
import json
import os
import sys
from pathlib import Path


def validate_workspace(workspace, installation):
    raw = str(workspace)
    if raw.startswith(("\\\\", "//")) or any(value in raw for value in ("://", ";", "${")) or ":" in raw[2:]:
        raise ValueError("Workspace must be one local directory, without network paths or placeholders")
    workspace = Path(raw).expanduser().resolve()
    installation = Path(installation).resolve()
    if str(workspace).startswith(("\\\\", "//")):
        raise ValueError("Workspace must be a local directory")
    if installation.is_relative_to(workspace) or (workspace.is_relative_to(installation) and not workspace.is_relative_to(installation / "workspace")):
        raise ValueError("Use a separate disposable project workspace, outside the installation")
    return workspace


def discover_xpdf(environment=None):
    environment = os.environ if environment is None else environment
    program_data = environment.get("ProgramData", r"C:\ProgramData")
    if str(program_data).startswith(("\\\\", "//")) or "://" in str(program_data):
        raise ValueError("ProgramData must be local to discover the installed SCADAPack XPDF")
    candidates = sorted((Path(program_data) / "Schneider Electric" / "CommonControlExpert").glob("*/Xpdf/SCBForSCADAPack.xpdf"))
    candidates = [path for path in candidates if path.is_file()]
    if len(candidates) > 1:
        raise ValueError("Multiple SCADAPack XPDF files found; choose one using CE_MCP_XPDF_CONTEXT or --xpdf-context")
    return candidates[0].resolve() if candidates else None


def prepare_environment(installation, environment=None):
    environment = os.environ if environment is None else environment
    default = Path(environment.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "RemoteConnectMCP" / "workspace"
    workspace = validate_workspace(environment.get("CE_MCP_WORKSPACE") or default, installation)
    xpdf = None if environment.get("CE_MCP_XPDF_CONTEXT") else discover_xpdf(environment)
    workspace.mkdir(parents=True, exist_ok=True)
    environment.update({"CE_MCP_WORKSPACE": str(workspace), "CE_MCP_TOOL_PROFILE": "offline",
                        "CE_MCP_ENABLE_ONLINE": "0", "CE_MCP_READ_ROOTS": str(workspace),
                        "CE_MCP_WRITE_ROOTS": str(workspace)})
    if xpdf:
        environment["CE_MCP_XPDF_CONTEXT"] = str(xpdf)
    os.chdir(workspace)
    return workspace


def self_check():
    import pythoncom
    import pywintypes
    import win32com.client
    from remoteconnect_mcp import __version__, native_bridge

    source = native_bridge._source_path()
    if not source.is_file():
        raise ValueError("Portable server is missing the native bridge source")
    return {"version": __version__, "pywin32_imports": "passed", "native_bridge_source": "present",
            "vendor_runtime_started": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--configure-bundle", type=Path)
    parser.add_argument("--workspace")
    parser.add_argument("--xpdf-context")
    parser.add_argument("--remoteconnect-home", default="")
    args = parser.parse_args(argv)
    try:
        if args.self_check:
            print(json.dumps(self_check()))
        elif args.configure_bundle:
            from configure import configure

            configure(args.configure_bundle, args.workspace, args.xpdf_context, args.remoteconnect_home)
        else:
            if args.workspace or args.xpdf_context or args.remoteconnect_home:
                parser.error("Use --configure-bundle for installation options, or CE_MCP_WORKSPACE when launching")
            installation = Path(sys.executable).resolve().parent.parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
            prepare_environment(installation)
            from remoteconnect_mcp.server import main as serve

            serve()
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
