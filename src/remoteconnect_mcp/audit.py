"""Cross-project audit for paired RemoteConnect configuration and logic files."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from .bridge import ControlExpertBridge
from .bulk_edit import (
    BulkEditError,
    _validate_data_log_name,
    configuration_semantics,
    inspect_relationships,
    inspect_workbook,
)
from .native_bridge import export_configuration
from .remoteconnect import discover_bundle


def _type_name(value: object) -> str:
    return str(value or "").partition(" <")[0].strip()


def configuration_logic_variable_specs(workbook_path: str) -> list[dict]:
    """Return exact name/DDT declarations required by an x70 configuration XLS."""
    semantics = configuration_semantics(workbook_path)
    specs = []
    for identity in sorted(semantics["objects"], key=lambda item: str(item[0]).lower()):
        logic_type = _type_name(identity[2])
        if logic_type and logic_type.lower() != "none":
            specs.append({"name": str(identity[0]), "type": logic_type})
    return specs


def merge_configuration_logic_variables(
    configuration_specs: list[dict],
    requested_specs: list[dict] | None,
) -> tuple[list[dict], dict]:
    """Merge configuration-owned declarations with explicit user variables."""
    merged: list[dict] = []
    by_name: dict[str, dict] = {}
    for index, spec in enumerate(requested_specs or []):
        name = str(spec.get("name", "")).strip()
        type_name = str(spec.get("type", "")).strip()
        if not name or not type_name:
            raise ValueError(f"variables[{index}] requires non-empty name and type")
        key = name.lower()
        if key in by_name:
            raise ValueError(f"Duplicate logic variable name: {name}")
        copied = dict(spec)
        copied.update({"name": name, "type": type_name})
        by_name[key] = copied
        merged.append(copied)

    generated = []
    matched = []
    for required in configuration_specs:
        name = str(required["name"])
        type_name = str(required["type"])
        existing = by_name.get(name.lower())
        if existing is not None:
            if existing["name"] != name:
                raise ValueError(
                    f"Configuration object {name!r} requires identical logic-variable casing; "
                    f"received {existing['name']!r}"
                )
            if str(existing["type"]).lower() != type_name.lower():
                raise ValueError(
                    f"Configuration object {name!r} requires logic type {type_name!r}; "
                    f"received {existing['type']!r}"
                )
            matched.append(name)
            continue
        spec = {
            "name": name,
            "type": type_name,
            "comment": "Generated from RemoteConnect configuration object",
        }
        by_name[name.lower()] = spec
        merged.append(spec)
        generated.append(name)
    return merged, {
        "required_from_configuration": len(configuration_specs),
        "explicit_matches": len(matched),
        "generated_missing_variables": len(generated),
        "generated_names": generated,
    }


def compare_configuration_logic(
    configured_objects: set[tuple],
    logic_variables: list[dict],
    sections: list[dict],
) -> dict:
    """Compare stable object identities with logic variables and section XML."""
    variables = {str(item.get("name", "")).lower(): item for item in logic_variables}
    section_tokens: dict[str, set[str]] = {}
    for section in sections:
        key = f"{section['task']}/{section['section']}"
        section_tokens[key] = {
            token.lower()
            for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", section.get("xml", ""))
        }

    expected: list[dict] = []
    errors: list[dict] = []
    warnings: list[dict] = []
    configured_names: set[str] = set()
    matched = 0
    referenced = 0
    for identity in sorted(configured_objects, key=lambda item: str(item[0]).lower()):
        name = str(identity[0])
        data_type = str(identity[1] or "")
        logic_type = _type_name(identity[2])
        if not logic_type or logic_type.lower() == "none":
            continue
        configured_names.add(name.lower())
        variable = variables.get(name.lower())
        references = [key for key, tokens in section_tokens.items() if name.lower() in tokens]
        item = {
            "name": name,
            "configuration_data_type": data_type,
            "expected_logic_type": logic_type,
            "actual_logic_type": str(variable.get("type", "")) if variable else None,
            "referenced_by": references,
        }
        expected.append(item)
        if variable is None:
            errors.append({
                "kind": "missing_logic_variable",
                "object": name,
                "expected_type": logic_type,
            })
        elif str(variable.get("name")) != name:
            errors.append({
                "kind": "logic_variable_case_mismatch",
                "object": name,
                "actual_name": variable.get("name"),
            })
        elif str(variable.get("type", "")).lower() != logic_type.lower():
            errors.append({
                "kind": "logic_type_mismatch",
                "object": name,
                "expected_type": logic_type,
                "actual_type": variable.get("type"),
            })
        else:
            matched += 1
        if references:
            referenced += 1
        elif variable is not None:
            warnings.append({"kind": "object_not_referenced_in_logic", "object": name})

    extras = sorted(
        item["name"]
        for item in logic_variables
        if str(item.get("type", "")).upper().startswith("T_SPX70_")
        and str(item.get("name", "")).lower() not in configured_names
    )
    warnings.extend({"kind": "logic_object_not_in_configuration", "variable": name} for name in extras)
    return {
        "expected_object_variables": len(expected),
        "matched_object_variables": matched,
        "referenced_objects": referenced,
        "unreferenced_objects": len(expected) - referenced,
        "extra_logic_object_variables": len(extras),
        "objects": expected,
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }


def audit_remoteconnect_bundle(path: str, *, rebuild_logic: bool = True) -> dict:
    """Audit a PRJ/STU pair without modifying either source file."""
    bundle = discover_bundle(path)
    prj = bundle["files"].get("prj")
    logic_path = bundle.get("logic_file")
    if not prj or not logic_path:
        raise ValueError(f"A paired .PRJ and .STU/.STA are required: {path}")

    with tempfile.TemporaryDirectory(prefix="remoteconnect-audit-") as directory:
        workbook_path = Path(directory) / "configuration.xls"
        native_export = export_configuration(prj, str(workbook_path))
        workbook = inspect_workbook(str(workbook_path), limit=0)
        relationships = inspect_relationships(str(workbook_path))
        semantics = configuration_semantics(str(workbook_path))

        editor_errors: list[dict] = []
        for log_name, _location in semantics["data_logs"]:
            try:
                _validate_data_log_name(str(log_name), "data log name")
            except BulkEditError as exc:
                editor_errors.append({
                    "kind": "invalid_data_log_name",
                    "name": log_name,
                    "message": str(exc),
                })

        # Use an isolated bridge so an MCP client's existing editor session is untouched.
        logic = ControlExpertBridge()
        try:
            opened = logic.open_project(logic_path)
            variables = logic.list_variables(None, 100_000)
            structure = logic.get_project_structure()
            sections = []
            section_errors = []
            for task in structure.get("tasks", []):
                for section in task.get("sections", []):
                    try:
                        sections.append(logic.read_section(task["name"], section["name"]))
                    except Exception as exc:
                        section_errors.append({
                            "kind": "section_read_failed",
                            "task": task["name"],
                            "section": section["name"],
                            "message": str(exc),
                        })
            build = logic.build_project(True) if rebuild_logic else {"attempted": False}
        finally:
            logic.close_project(False)

    comparison = compare_configuration_logic(
        semantics["objects"], variables["variables"], sections
    )
    errors = [*editor_errors, *section_errors, *comparison["errors"]]
    if not relationships["ok"]:
        errors.extend(relationships["issues"])
    build_ok = not rebuild_logic or build.get("build_state") == "built_ok"
    if not build_ok:
        errors.append({
            "kind": "logic_build_failed",
            "build_state": build.get("build_state"),
            "output": build.get("output"),
        })
    return {
        "bundle": bundle,
        "source_modified": False,
        "ui_automation": False,
        "native_export": {
            "ok": native_export["ok"],
            "sheet_count": len(workbook["sheets"]),
        },
        "configuration": {
            "object_count": len(semantics["objects"]),
            "data_log_count": len(semantics["data_logs"]),
            "modbus_scanner_count": len(semantics["modbus_scanners"]),
            "dnp_point_count": len(semantics["dnp_points"]),
            "relationships": relationships,
            "live_editor_rule_errors": editor_errors,
        },
        "logic": {
            "opened": opened,
            "total_variables": variables["total_variables"],
            "structure": structure,
            "sections_read": len(sections),
            "section_read_errors": section_errors,
            "build": build,
        },
        "synchronization": comparison,
        "errors": errors,
        "warnings": comparison["warnings"],
        "error_count": len(errors),
        "warning_count": len(comparison["warnings"]),
        "ok": not errors,
    }
