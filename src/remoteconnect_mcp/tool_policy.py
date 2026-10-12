"""Tool discovery and filesystem boundaries for local MCP clients."""

from __future__ import annotations

import os
from pathlib import Path


READ_TOOLS = frozenset({
    "get_status", "inspect_remoteconnect_project", "inventory_remoteconnect_configuration",
    "read_remoteconnect_feedback", "read_remoteconnect_import_report",
    "inspect_remoteconnect_bulk_edit_workbook", "inspect_remoteconnect_configuration_relationships",
    "get_project_structure", "list_data_types", "list_variables", "get_language_reference",
    "read_section", "read_st_source", "validate_xml", "get_project_setting",
    "inspect_parameter_csv", "get_capabilities",
})
SESSION_TOOLS = frozenset({"open_project", "open_remoteconnect_logic", "close_project"})
OFFLINE_TOOLS = READ_TOOLS | SESSION_TOOLS | frozenset({
    "audit_remoteconnect_project", "create_remoteconnect_bulk_edit_copy",
    "create_remoteconnect_objects_copy", "create_remoteconnect_parent_entities_copy",
    "create_remoteconnect_configuration_project", "create_remoteconnect_project",
    "export_remoteconnect_configuration", "apply_remoteconnect_configuration_copy",
    "build_remoteconnect_logic_copy", "save_project", "build_project", "analyze_project",
    "create_variable", "update_variable", "delete_variable", "write_st_logic",
    "create_section", "delete_section", "import_xml", "export_xml", "export_project",
    "create_parameter_csv_copy",
})
ONLINE_TOOLS = frozenset({
    "start_simulator", "stop_simulator", "plc_setup_connection", "plc_connect",
    "plc_disconnect", "plc_state", "plc_transfer", "plc_command", "modbus_connect",
    "modbus_disconnect", "modbus_status", "read_tags", "write_tags",
})
READ_PATHS = frozenset({"path", "source_path", "template_path", "workbook_path",
                        "configuration_workbook", "file_path", "log_path"})
WRITE_PATHS = frozenset({"output_path", "project_path"})


class ToolPolicy:
    def __init__(self, environment=None, cwd=None):
        env = os.environ if environment is None else environment
        self.profile = env.get("CE_MCP_TOOL_PROFILE", "offline").strip().lower()
        if self.profile not in {"inspect", "offline", "full"}:
            raise ValueError("CE_MCP_TOOL_PROFILE must be inspect, offline or full")
        self.online = self.profile == "full" and env.get("CE_MCP_ENABLE_ONLINE", "").strip().lower() in {"1", "true", "yes"}
        base = Path(cwd or Path.cwd()).resolve()
        self.read_roots = self._roots(env.get("CE_MCP_READ_ROOTS"), base)
        self.write_roots = self._roots(env.get("CE_MCP_WRITE_ROOTS"), base)

    @staticmethod
    def _roots(value, base):
        return tuple(Path(p).expanduser().resolve() for p in value.split(os.pathsep) if p.strip()) if value else (base,)

    def allows(self, name):
        if name in ONLINE_TOOLS:
            return self.online
        return self.profile == "full" or name in (READ_TOOLS | SESSION_TOOLS if self.profile == "inspect" else OFFLINE_TOOLS)

    def check_path(self, value, *, write=False):
        raw = str(value)
        # UNC paths could cause network access before path resolution.
        if raw.startswith(("\\\\", "//")) or "://" in raw:
            raise ValueError("Network paths are not permitted")
        if os.name == "nt" and ":" in raw[2:]:
            raise ValueError("Alternate data stream paths are not permitted")
        path = Path(raw).expanduser().resolve()
        roots = self.write_roots if write else self.read_roots
        if not any(path.is_relative_to(root) for root in roots):
            raise ValueError(f"Path is outside CE_MCP_{'WRITE' if write else 'READ'}_ROOTS: {path}")
        return path

    def check_arguments(self, name, arguments, *, project_path=None):
        for key, value in arguments.items():
            if not value or key not in READ_PATHS | WRITE_PATHS:
                continue
            write = key in WRITE_PATHS or (key == "path" and name in {"save_project", "export_project"})
            self.check_path(value, write=write)
            # Bundle discovery follows siblings. Validate them before any runtime opens them.
            if not write and Path(str(value)).suffix.lower() in {".prj", ".rcz", ".stu", ".sta"}:
                from .remoteconnect import discover_bundle
                for member in discover_bundle(str(value))["files"].values():
                    self.check_path(member)
        # Validate inline exchange documents before handing them to vendor parsers.
        from .xml_safe import parse_xml_bytes, parse_xml_file
        for key in ("xml_content", "xml", "settings_xso"):
            if arguments.get(key):
                parse_xml_bytes(str(arguments[key]).encode("utf-8"))
        if name == "import_xml" and arguments.get("file_path"):
            parse_xml_file(arguments["file_path"])
        if name == "read_remoteconnect_feedback" and not arguments.get("log_path"):
            raise ValueError("Supply an explicit log_path inside CE_MCP_READ_ROOTS")
        if name == "save_project" or (name == "close_project" and arguments.get("save")):
            target = arguments.get("path") or project_path
            if not target:
                raise ValueError("Saving requires an explicit approved project path")
            self.check_path(target, write=True)
        if self.profile == "inspect" and name == "close_project" and arguments.get("save"):
            raise ValueError("The inspect profile cannot save projects")
