"""Cross-project audit for paired RemoteConnect configuration and logic files."""

from __future__ import annotations

import hashlib
import re
import shutil
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
from .xml_safe import parse_xml_bytes


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_PATH_COMPONENT = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[\s*(-?\d+(?:\s*,\s*-?\d+)*)\s*\]")
_ARRAY_TYPE = re.compile(r"ARRAY\s*\[([^\]]+)\]\s*OF\s*(.+)\Z", re.IGNORECASE)
_ELEMENTARY_TYPES = frozenset({"BOOL", "EBOOL", "INT", "UINT", "DINT", "UDINT", "REAL", "LREAL", "BYTE", "WORD", "DWORD", "TIME", "DATE", "TOD", "DT", "STRING"})


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_without_comments(text: str) -> str:
    """Remove ST comments and strings without exposing tokens inside them."""
    result = []
    position, depth = 0, 0
    while position < len(text):
        pair = text[position:position + 2]
        if pair == "(*":
            if not depth:
                result.append(" ")
            depth += 1
            position += 2
        elif depth:
            if pair == "*)":
                depth -= 1
                position += 2
            else:
                position += 1
        elif pair == "//":
            newline = text.find("\n", position)
            position = len(text) if newline < 0 else newline
            result.append(" ")
        elif text[position] in {"'", '"'}:
            quote = text[position]
            position += 1
            while position < len(text):
                if text[position] == "$":
                    position += 2
                elif text[position:position + 2] == quote * 2:
                    position += 2
                elif text[position] == quote:
                    position += 1
                    break
                else:
                    position += 1
            result.append(" ")
        else:
            result.append(text[position])
            position += 1
    return "".join(result)


def _logic_path(name: str):
    base = re.match(r"[A-Za-z_][A-Za-z0-9_]*", name)
    if base is None:
        return None
    components = []
    position = base.end()
    while position < len(name):
        match = _PATH_COMPONENT.match(name, position)
        if match is None:
            return None
        if match.group(1) is not None:
            components.append(("member", match.group(1)))
        else:
            components.append(("index", tuple(int(value.strip()) for value in match.group(2).split(","))))
        position = match.end()
    return base.group(), components


def _array_type(type_name: str):
    match = _ARRAY_TYPE.fullmatch(type_name.strip())
    if match is None:
        return None
    bounds = []
    for dimension in match.group(1).split(","):
        interval = re.fullmatch(r"\s*(-?\d+)\s*\.\.\s*(-?\d+)\s*", dimension)
        if interval is None:
            return None
        lower, upper = map(int, interval.groups())
        if lower > upper:
            return None
        bounds.append((lower, upper))
    return bounds, match.group(2).strip()


def parse_native_logic_definitions(xml_content: str) -> dict:
    """Read declared DDT members and exported public FB parameters.

    Protected or absent type definitions remain unknown. No members or array
    bounds are inferred from an object's name or expected configuration type.
    """
    root = parse_xml_bytes(xml_content.encode("utf-8"))
    definitions = {}
    for source in root.iter():
        tag = source.tag.rsplit("}", 1)[-1]
        if tag not in {"DDTSource", "FBSource"}:
            continue
        name = source.attrib.get("DDTName" if tag == "DDTSource" else "nameOfFBType", "")
        if not name:
            continue
        members = []
        groups = {"structure"} if tag == "DDTSource" else {"inputParameters", "outputParameters", "inOutParameters", "publicLocalVariables"}
        found_groups = False
        for group in source.iter():
            if group.tag.rsplit("}", 1)[-1] not in groups:
                continue
            found_groups = True
            for member in group:
                if member.tag.rsplit("}", 1)[-1] == "variables" and member.attrib.get("name"):
                    members.append({"name": member.attrib["name"], "type": member.attrib.get("typeName", "")})
        definition = {"name": name, "members": members, "complete": tag == "DDTSource" and found_groups}
        member_names = [member["name"].lower() for member in members]
        if len(member_names) != len(set(member_names)):
            raise ValueError(f"Duplicate native member names in {name}")
        existing = definitions.get(name.lower())
        if existing is not None and existing != definition:
            raise ValueError(f"Conflicting native type definitions for {name}")
        definitions[name.lower()] = definition
    return definitions


def _resolve_logic_object(name: str, variables: dict, definitions: dict) -> dict:
    parsed = _logic_path(name)
    if parsed is None:
        return {"status": "unverified", "kind": "unsupported_logic_object_path", "reason": "Object path syntax is unsupported"}
    base, components = parsed
    variable = variables.get(base.lower())
    if variable is None:
        return {"status": "error", "kind": "missing_logic_variable", "base": base}
    actual_name = str(variable.get("name", ""))
    type_name = str(variable.get("type", "")).strip()
    case_mismatch = actual_name != base
    evidence = []
    for kind, value in components:
        if not type_name:
            return {"status": "unverified", "kind": "logic_type_unverified", "base": base, "reason": "Native declaration has no type"}
        if kind == "index":
            array = _array_type(type_name)
            if array is None:
                known = type_name.upper() in _ELEMENTARY_TYPES or definitions.get(type_name.lower(), {}).get("complete")
                return {"status": "error" if known else "unverified", "kind": "logic_not_an_array" if known else "logic_array_type_unverified", "base": base, "actual_type": type_name, "reason": "No native numeric array bounds are available"}
            bounds, element_type = array
            if len(bounds) != len(value):
                return {"status": "error", "kind": "logic_array_dimension_mismatch", "base": base, "indices": list(value), "bounds": bounds}
            if any(index < lower or index > upper for index, (lower, upper) in zip(value, bounds)):
                return {"status": "error", "kind": "logic_array_index_out_of_bounds", "base": base, "indices": list(value), "bounds": bounds}
            evidence.append({"array_type": type_name, "indices": list(value), "bounds": bounds})
            actual_name += "[" + ",".join(map(str, value)) + "]"
            type_name = element_type
        else:
            definition = definitions.get(type_name.lower())
            if definition is None:
                return {"status": "unverified", "kind": "logic_member_type_unverified", "base": base, "actual_type": type_name, "reason": "The native member definition is unavailable"}
            members = {str(member.get("name", "")).lower(): member for member in definition.get("members", [])}
            member = members.get(value.lower())
            if member is None:
                return {"status": "error" if definition.get("complete") else "unverified", "kind": "missing_logic_member" if definition.get("complete") else "logic_member_unverified", "base": base, "member": value, "actual_type": type_name, "reason": "Member is absent from the exported definition"}
            case_mismatch |= str(member["name"]) != value
            actual_name += "." + str(member["name"])
            evidence.append({"declaring_type": type_name, "member": str(member["name"]), "member_type": str(member.get("type", ""))})
            type_name = str(member.get("type", "")).strip()
    if not type_name:
        return {"status": "unverified", "kind": "logic_type_unverified", "base": base, "reason": "The native element or member type is unavailable"}
    return {"status": "resolved", "base": base, "actual_name": actual_name, "actual_type": type_name, "case_mismatch": case_mismatch, "evidence": evidence}


def _type_name(value: object) -> str:
    return str(value or "").partition(" <")[0].strip()


def configuration_logic_variable_specs(workbook_path: str) -> list[dict]:
    """Return exact name/DDT declarations required by an x70 configuration XLS."""
    semantics = configuration_semantics(workbook_path)
    specs = []
    for identity in sorted(semantics["objects"], key=lambda item: str(item[0]).lower()):
        logic_type = _type_name(identity[2])
        if logic_type and logic_type.lower() != "none":
            if not _IDENTIFIER.fullmatch(str(identity[0])):
                raise ValueError(
                    f"Configuration object {identity[0]!r} is an array element or member path. "
                    "Automatic declaration requires a simple variable name; provide and "
                    "validate the complete native base array or structured declaration first."
                )
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
        if not _IDENTIFIER.fullmatch(name):
            raise ValueError(f"Logic declaration {name!r} must use a simple identifier, not an element or member path")
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
        if not _IDENTIFIER.fullmatch(name):
            raise ValueError(f"Configuration declaration {name!r} requires a validated base declaration")
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
    *,
    type_definitions: dict | None = None,
) -> dict:
    """Resolve object paths against native declarations, checking every index
    and member before comparing the terminal type. Unknown definitions make
    verification incomplete rather than producing a false missing-variable error.
    """
    variables = {str(item.get("name", "")).lower(): item for item in logic_variables}
    definitions = {str(name).lower(): value for name, value in (type_definitions or {}).items()}
    section_tokens: dict[str, set[str]] = {}
    section_text: dict[str, str] = {}
    for section in sections:
        key = f"{section['task']}/{section['section']}"
        text = section.get("xml", "")
        if text.lstrip().startswith("<"):
            try:
                root = parse_xml_bytes(text.encode("utf-8"))
                sources = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "STSource"]
                if sources:
                    text = _source_without_comments("\n".join("".join(source.itertext()) for source in sources))
            except Exception:
                # Section reads have their own diagnostics. Keep reference
                # evidence lexical if this export is not an ST source document.
                pass
        else:
            text = _source_without_comments(text)
        section_text[key] = text
        section_tokens[key] = {
            token.lower()
            for token in re.findall(r"(?<![A-Za-z0-9_.])([A-Za-z_][A-Za-z0-9_]*)", text)
        }

    expected: list[dict] = []
    errors: list[dict] = []
    warnings: list[dict] = []
    unverified: list[dict] = []
    configured_names: set[str] = set()
    matched = 0
    referenced = 0
    base_referenced = 0
    for identity in sorted(configured_objects, key=lambda item: str(item[0]).lower()):
        name = str(identity[0])
        data_type = str(identity[1] or "")
        logic_type = _type_name(identity[2])
        if not logic_type or logic_type.lower() == "none":
            continue
        resolution = _resolve_logic_object(name, variables, definitions)
        base = resolution.get("base", name)
        configured_names.add(str(base).lower())
        exact_pattern = re.compile(r"(?<![A-Za-z0-9_.])" + re.escape(name) + r"(?![A-Za-z0-9_])", re.IGNORECASE)
        references = [key for key, text in section_text.items() if exact_pattern.search(text)]
        base_references = [key for key, tokens in section_tokens.items() if str(base).lower() in tokens]
        item = {
            "name": name,
            "configuration_data_type": data_type,
            "expected_logic_type": logic_type,
            "actual_logic_type": resolution.get("actual_type"),
            "base_variable": base,
            "resolved_name": resolution.get("actual_name"),
            "resolution_evidence": resolution.get("evidence", []),
            "referenced_by": references,
            "base_referenced_by": base_references,
            "reference_evidence": "literal_path" if references else "base_only" if base_references else "none",
        }
        expected.append(item)
        if resolution["status"] == "unverified":
            uncertainty = {"object": name, "expected_type": logic_type, **resolution}
            unverified.append(uncertainty)
            warnings.append(uncertainty)
            item["verification"] = "unverified"
        elif resolution["status"] == "error":
            errors.append({"object": name, "expected_type": logic_type, **resolution})
            item["verification"] = "error"
        elif resolution["case_mismatch"]:
            errors.append({
                "kind": "logic_variable_case_mismatch",
                "object": name,
                "actual_name": resolution["actual_name"],
            })
            item["verification"] = "error"
        elif str(resolution["actual_type"]).lower() != logic_type.lower():
            errors.append({
                "kind": "logic_type_mismatch",
                "object": name,
                "expected_type": logic_type,
                "actual_type": resolution["actual_type"],
            })
            item["verification"] = "error"
        else:
            matched += 1
            item["verification"] = "verified"
        if references:
            referenced += 1
        elif resolution["status"] == "resolved" and not base_references:
            warnings.append({"kind": "object_not_referenced_in_logic", "object": name})
        if base_references:
            base_referenced += 1

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
        "base_referenced_objects": base_referenced,
        "unreferenced_objects": len(expected) - referenced,
        "extra_logic_object_variables": len(extras),
        "objects": expected,
        "errors": errors,
        "warnings": warnings,
        "unverified_objects": unverified,
        "unverified_object_variables": len(unverified),
        "verification_complete": not unverified,
        "reference_validation": "Lexical source occurrences; a base-only occurrence does not establish individual element or member use",
        "ok": not errors and not unverified,
    }


def audit_remoteconnect_bundle(path: str, *, rebuild_logic: bool = True) -> dict:
    """Audit a PRJ/STU pair without modifying either source file."""
    bundle = discover_bundle(path)
    prj = bundle["files"].get("prj")
    logic_path = bundle.get("logic_file")
    if not prj or not logic_path:
        raise ValueError(f"A paired .PRJ and .STU/.STA are required: {path}")
    source_hashes_before = {source: _file_sha256(source) for source in (prj, logic_path)}

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
            staged_logic = Path(directory) / Path(logic_path).name
            shutil.copy2(logic_path, staged_logic)
            opened = logic.open_project(str(staged_logic))
            variables = logic.list_variables(None, 100_000)
            type_export_errors = []
            definitions = {}
            try:
                native_variables = logic.export_xml("variables", None, None)
                if "xml" in native_variables:
                    variable_xml = native_variables["xml"]
                else:
                    with Path(native_variables["file"]).open("rb") as stream:
                        variable_bytes = stream.read(128 * 1024 * 1024 + 1)
                    if len(variable_bytes) > 128 * 1024 * 1024:
                        raise ValueError("Native variable XML exceeds the inspection limit")
                    variable_xml = variable_bytes.decode("utf-8-sig")
                definitions = parse_native_logic_definitions(variable_xml)
            except Exception as exc:
                type_export_errors.append({"kind": "native_type_definitions_unavailable", "message": str(exc)})
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
            try:
                logic.close_project(False)
            finally:
                logic.shutdown()

    comparison = compare_configuration_logic(
        semantics["objects"], variables["variables"], sections, type_definitions=definitions
    )
    errors = [*editor_errors, *section_errors, *comparison["errors"]]
    source_hashes_after = {source: _file_sha256(source) for source in source_hashes_before}
    changed_sources = [source for source, digest in source_hashes_before.items() if source_hashes_after[source] != digest]
    if changed_sources:
        errors.append({"kind": "source_changed_during_audit", "paths": changed_sources, "message": "Source hashes changed; the audit does not establish a consistent source snapshot"})
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
        "source_modified": bool(changed_sources),
        "source_hashes_before": source_hashes_before,
        "source_hashes_after": source_hashes_after,
        "source_hashes_unchanged": not changed_sources,
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
            "native_type_definitions": len(definitions),
            "type_definition_export_errors": type_export_errors,
            "build": build,
        },
        "synchronization": comparison,
        "errors": errors,
        "warnings": [*comparison["warnings"], *type_export_errors],
        "error_count": len(errors),
        "warning_count": len(comparison["warnings"]) + len(type_export_errors),
        "verification_complete": comparison["verification_complete"],
        "ok": not errors and comparison["verification_complete"],
    }
