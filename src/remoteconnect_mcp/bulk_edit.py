"""Safe readers and copy-only writers for RemoteConnect Object Bulk Edit XLS files."""

from __future__ import annotations

import os
import re
from pathlib import Path


class BulkEditError(ValueError):
    pass


def _open(path: str, *, formatting: bool = False):
    import xlrd

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise BulkEditError(f"Workbook not found: {source}")
    if source.suffix.lower() != ".xls":
        raise BulkEditError("RemoteConnect Object Bulk Edit workbooks must use .xls")
    try:
        return source, xlrd.open_workbook(str(source), formatting_info=formatting)
    except Exception as exc:
        raise BulkEditError(f"Could not read RemoteConnect workbook: {exc}") from exc


def _sheet_schema(sheet) -> dict:
    labels = [str(sheet.cell_value(0, col)) for col in range(sheet.ncols)]
    fields = [str(sheet.cell_value(1, col)) for col in range(sheet.ncols)]
    return {
        "name": sheet.name,
        "row_count": max(0, sheet.nrows - 2),
        "columns": [
            {"field": field, "label": labels[index], "column": index + 1}
            for index, field in enumerate(fields)
            if field
        ],
    }


def inspect_workbook(path: str, sheet_name: str | None = None, limit: int = 100) -> dict:
    if limit < 0 or limit > 5000:
        raise BulkEditError("limit must be between 0 and 5000")
    source, book = _open(path)
    settings = book.sheet_by_index(0)
    metadata = {
        str(settings.cell_value(row, 0)): settings.cell_value(row, 2)
        for row in range(1, settings.nrows)
    }
    schemas = [_sheet_schema(book.sheet_by_index(i)) for i in range(book.nsheets)]
    result = {
        "path": str(source),
        "format": "RemoteConnect Object Bulk Edit XLS",
        "metadata": metadata,
        "sheets": schemas,
    }
    if sheet_name:
        try:
            sheet = book.sheet_by_name(sheet_name)
        except Exception as exc:
            raise BulkEditError(
                f"Sheet not found: {sheet_name}. Available: {book.sheet_names()}"
            ) from exc
        fields = [str(sheet.cell_value(1, col)) for col in range(sheet.ncols)]
        rows = []
        for row_index in range(2, min(sheet.nrows, 2 + limit)):
            rows.append({
                field: sheet.cell_value(row_index, col)
                for col, field in enumerate(fields)
                if field
            })
        result["selected"] = {**_sheet_schema(sheet), "rows": rows}
    return result


def _normalize(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


RELATIONSHIPS = (
    ("physical_io_object", "(3) Physical IO", "ObjSequenceId", "(2) Objects", "ObjSequenceId", True),
    ("physical_channel_module", "(4) Physical IO Channels", "ModuleId", "(3) Physical IO", "ModuleId", False),
    ("physical_channel_object", "(4) Physical IO Channels", "ObjSequenceId", "(2) Objects", "ObjSequenceId", True),
    ("dnp_point_device", "(6) DNP3 Controlling Station Po", "RemoteDeviceId", "(5) DNP3 Controlling Station De", "DeviceSequenceId", False),
    ("dnp_device_status_mapping", "(11) DNP3 Controlling Station D", "DeviceSequenceId", "(5) DNP3 Controlling Station De", "DeviceSequenceId", False),
    ("dnp_device_status_object", "(11) DNP3 Controlling Station D", "ObjSequenceId", "(2) Objects", "ObjSequenceId", True),
    ("dnp_point_object", "(12) DNP3 Controlling Station P", "ObjSequenceId", "(2) Objects", "ObjSequenceId", True),
    ("dnp_point_mapping", "(12) DNP3 Controlling Station P", "PointSequenceId", "(6) DNP3 Controlling Station Po", "RemotePointSequenceId", False),
    ("modbus_scanner_device", "(10) Modbus Scanners", "DeviceSequenceId", "(9) Modbus Server Devices", "DeviceSequenceId", False),
    ("modbus_server_object", "(13) Modbus Server Device - Obj", "ObjSequenceId", "(2) Objects", "ObjSequenceId", True),
    ("modbus_server_mapping", "(13) Modbus Server Device - Obj", "DeviceSequenceId", "(9) Modbus Server Devices", "DeviceSequenceId", False),
    ("modbus_scanner_object", "(14) Modbus Scanner - Obj", "ObjSequenceId", "(2) Objects", "ObjSequenceId", True),
    ("modbus_scanner_mapping", "(14) Modbus Scanner - Obj", "PointScannerSequenceId", "(10) Modbus Scanners", "ScannerSequenceId", False),
    # Native exports may intentionally leave Browser ObjSequenceId blank and
    # identify the target by ObjectName alone.
    ("browser_object", "(22) Browser Objects", "ObjSequenceId", "(2) Objects", "ObjSequenceId", True),
    ("browser_list", "(22) Browser Objects", "BrowserReferenceId", "(21) Browser Lists", "BrowserReferenceId", False),
    ("object_data_log", "(2) Objects", "DataLoggingLogFileName", "(26) Data Logs", "LogName", True),
)


def _sheet_with_prefix(book, prefix: str):
    matches = [sheet for sheet in book.sheets() if sheet.name.startswith(prefix)]
    if len(matches) != 1:
        raise BulkEditError(f"Expected one sheet beginning {prefix!r}, found {len(matches)}")
    return matches[0]


def _rows_by_prefix(book, prefix: str) -> list[dict]:
    sheet = _sheet_with_prefix(book, prefix)
    fields = [str(sheet.cell_value(1, col)) for col in range(sheet.ncols)]
    return [
        {
            field: _normalize(sheet.cell_value(row, col))
            for col, field in enumerate(fields)
            if field
        }
        for row in range(2, sheet.nrows)
    ]


def inspect_relationships(path: str, *, max_issues: int = 200) -> dict:
    """Validate the native workbook's primary keys and cross-sheet references."""
    if max_issues < 1 or max_issues > 5000:
        raise BulkEditError("max_issues must be between 1 and 5000")
    source, book = _open(path)
    prefixes = {item for relation in RELATIONSHIPS for item in (relation[1], relation[3])}
    prefixes.add("(28) Legacy DLOG")
    tables = {prefix: _rows_by_prefix(book, prefix) for prefix in prefixes}
    issues: list[dict] = []
    relations = []

    unique_keys = {
        # DNP3 point numbers and Modbus registers are scoped by object/data
        # type in native exports and are therefore not globally unique.
        "(2) Objects": ("ObjSequenceId", "ObjName"),
        "(3) Physical IO": ("ModuleId",),
        "(5) DNP3 Controlling Station De": ("DeviceSequenceId", "DeviceName"),
        "(6) DNP3 Controlling Station Po": ("RemotePointSequenceId",),
        "(9) Modbus Server Devices": ("DeviceSequenceId", "DeviceName"),
        "(10) Modbus Scanners": ("ScannerSequenceId",),
        "(21) Browser Lists": ("BrowserReferenceId", "Name"),
    }
    for table, keys in unique_keys.items():
        for key in keys:
            seen: dict[object, int] = {}
            for row_index, row in enumerate(tables[table], 3):
                value = row.get(key, "")
                if value == "" or (key in {"Dnp3PointNumber", "ModbusRegister"} and value == 0):
                    continue
                if value in seen and len(issues) < max_issues:
                    issues.append({
                        "kind": "duplicate_key",
                        "table": table,
                        "field": key,
                        "value": value,
                        "rows": [seen[value], row_index],
                    })
                seen[value] = row_index

    for name, child_table, child_key, parent_table, parent_key, nullable in RELATIONSHIPS:
        parent_values = {
            row.get(parent_key) for row in tables[parent_table] if row.get(parent_key, "") != ""
        }
        unresolved = 0
        checked = 0
        for row_index, row in enumerate(tables[child_table], 3):
            value = row.get(child_key, "")
            if value == "" and nullable:
                continue
            checked += 1
            if value not in parent_values:
                unresolved += 1
                if len(issues) < max_issues:
                    issues.append({
                        "kind": "unresolved_reference",
                        "relationship": name,
                        "table": child_table,
                        "field": child_key,
                        "value": value,
                        "row": row_index,
                        "target_table": parent_table,
                        "target_field": parent_key,
                    })
        relations.append({"name": name, "checked": checked, "unresolved": unresolved})

    objects = {row.get("ObjSequenceId"): row for row in tables["(2) Objects"]}
    object_names = {row.get("ObjName") for row in tables["(2) Objects"]}
    for row_index, browser in enumerate(tables["(22) Browser Objects"], 3):
        obj = objects.get(browser.get("ObjSequenceId"))
        if obj and browser.get("ObjectName") != obj.get("ObjName") and len(issues) < max_issues:
            issues.append({
                "kind": "mismatched_reference_label",
                "relationship": "browser_object",
                "row": row_index,
                "expected": obj.get("ObjName"),
                "actual": browser.get("ObjectName"),
            })
        elif not obj and browser.get("ObjectName") not in object_names and len(issues) < max_issues:
            issues.append({
                "kind": "unresolved_reference",
                "relationship": "browser_object_name",
                "row": row_index,
                "value": browser.get("ObjectName"),
                "target_table": "(2) Objects",
                "target_field": "ObjName",
            })
    dnp_devices = {
        row.get("DeviceSequenceId"): row for row in tables["(5) DNP3 Controlling Station De"]
    }
    for row_index, point in enumerate(tables["(6) DNP3 Controlling Station Po"], 3):
        device = dnp_devices.get(point.get("RemoteDeviceId"))
        if device and point.get("RemoteDeviceName") != device.get("DeviceName") and len(issues) < max_issues:
            issues.append({
                "kind": "mismatched_reference_label",
                "relationship": "dnp_point_device",
                "row": row_index,
                "expected": device.get("DeviceName"),
                "actual": point.get("RemoteDeviceName"),
            })
    modbus_devices = {
        row.get("DeviceSequenceId"): row for row in tables["(9) Modbus Server Devices"]
    }
    scanners = {
        row.get("ScannerSequenceId"): row for row in tables["(10) Modbus Scanners"]
    }
    for row_index, scanner in enumerate(tables["(10) Modbus Scanners"], 3):
        device = modbus_devices.get(scanner.get("DeviceSequenceId"))
        if device and scanner.get("DeviceName") != device.get("DeviceName") and len(issues) < max_issues:
            issues.append({
                "kind": "mismatched_reference_label",
                "relationship": "modbus_scanner_device",
                "row": row_index,
                "expected": device.get("DeviceName"),
                "actual": scanner.get("DeviceName"),
            })
    for row_index, mapping in enumerate(tables["(14) Modbus Scanner - Obj"], 3):
        scanner = scanners.get(mapping.get("PointScannerSequenceId"))
        obj = objects.get(mapping.get("ObjSequenceId"))
        if scanner:
            address = mapping.get("ModbusRegisterAddress")
            start = scanner.get("RegisterStartAddr")
            quantity = scanner.get("RegisterQuantity")
            if all(isinstance(value, (int, float)) for value in (address, start, quantity)):
                if not (start <= address < start + quantity) and len(issues) < max_issues:
                    issues.append({
                        "kind": "out_of_range_reference",
                        "relationship": "modbus_scanner_mapping",
                        "row": row_index,
                        "address": address,
                        "scanner_start": start,
                        "scanner_quantity": quantity,
                    })
    for row_index, legacy_log in enumerate(tables["(28) Legacy DLOG"], 3):
        for field_number in range(1, 9):
            field = f"Field{field_number}"
            value = legacy_log.get(field, "")
            if value and value not in object_names and len(issues) < max_issues:
                issues.append({
                    "kind": "unresolved_reference",
                    "relationship": "legacy_data_log_object",
                    "table": "(28) Legacy DLOG",
                    "field": field,
                    "value": value,
                    "row": row_index,
                    "target_table": "(2) Objects",
                    "target_field": "ObjName",
                })
    return {
        "path": str(source),
        "relationships": relations,
        "issues": issues,
        "issue_count": len(issues),
        "issues_truncated": len(issues) >= max_issues,
        "ok": not issues,
    }


def create_objects_copy(
    template_path: str,
    output_path: str,
    objects: list[dict],
    *,
    overwrite: bool = False,
) -> dict:
    """Create objects and their dependent table relationships in one workbook."""
    if not objects:
        raise BulkEditError("objects must contain at least one object specification")
    _, book = _open(template_path)
    object_rows = _rows_by_prefix(book, "(2) Objects")
    object_names = {row.get("ObjName") for row in object_rows}
    sequence_values = [
        int(row["ObjSequenceId"])
        for row in object_rows
        if isinstance(row.get("ObjSequenceId"), (int, float))
    ]
    next_sequence = max(sequence_values, default=-1) + 1
    next_object_value = {}
    for field in ("Dnp3PointNumber", "ModbusRegister", "Iec104MonitorIoa", "Iec104ControlIoa"):
        values = [
            int(row[field]) for row in object_rows
            if isinstance(row.get(field), (int, float)) and row[field] > 0
        ]
        next_object_value[field] = max(values, default=0) + 1
    browser_lists = _rows_by_prefix(book, "(21) Browser Lists")
    browser_rows = _rows_by_prefix(book, "(22) Browser Objects")
    modbus_devices = _rows_by_prefix(book, "(9) Modbus Server Devices")
    scanner_rows = _rows_by_prefix(book, "(10) Modbus Scanners")
    scanner_mapping_rows = _rows_by_prefix(book, "(14) Modbus Scanner - Obj")
    data_logs = _rows_by_prefix(book, "(26) Data Logs")

    patches: list[dict] = []
    additions: list[dict] = []
    created = []

    # RemoteConnect 3.0 exports can leave Browser ObjSequenceId blank even
    # though their own Replace-all importer requires it. Repair that native
    # export asymmetry using the stable ObjectName relationship.
    object_sequence_by_name = {
        row.get("ObjName"): row.get("ObjSequenceId") for row in object_rows
    }
    for browser in browser_rows:
        if browser.get("ObjSequenceId", "") != "":
            continue
        object_sequence = object_sequence_by_name.get(browser.get("ObjectName"))
        if object_sequence is None:
            continue
        patches.append({
            "sheet": _sheet_with_prefix(book, "(22) Browser Objects").name,
            "match": {
                "BrowserReferenceId": browser.get("BrowserReferenceId"),
                "ObjectName": browser.get("ObjectName"),
            },
            "values": {"ObjSequenceId": object_sequence},
        })

    def unique(rows, match, label):
        matches = [row for row in rows if all(row.get(key) == _normalize(value) for key, value in match.items())]
        if len(matches) != 1:
            raise BulkEditError(f"{label} selected {len(matches)} rows; exactly one is required: {match}")
        return matches[0]

    for index, spec in enumerate(objects):
        name = str(spec.get("name", "")).strip()
        prototype = str(spec.get("prototype", "")).strip()
        if not name or not prototype:
            raise BulkEditError(f"objects[{index}] requires name and prototype")
        if name in object_names:
            raise BulkEditError(f"Object name already exists: {name}")
        prototype_row = unique(object_rows, {"ObjName": prototype}, f"objects[{index}].prototype")
        sequence_id = next_sequence
        next_sequence += 1
        object_names.add(name)
        object_values = dict(spec.get("values") or {})
        for field in ("Dnp3PointNumber", "ModbusRegister", "Iec104MonitorIoa", "Iec104ControlIoa"):
            if field not in object_values and isinstance(prototype_row.get(field), (int, float)) and prototype_row[field] > 0:
                object_values[field] = next_object_value[field]
                next_object_value[field] += 1
        object_values.update({"ObjName": name, "ObjSequenceId": sequence_id})
        additions.append({
            "sheet": _sheet_with_prefix(book, "(2) Objects").name,
            "clone": {"ObjName": prototype},
            "values": object_values,
        })

        linked = []
        for link_index, link in enumerate(spec.get("relationships") or []):
            kind = str(link.get("kind", "")).strip()
            values = dict(link.get("values") or {})
            label = f"objects[{index}].relationships[{link_index}]"
            if kind == "browser":
                list_name = link.get("list_name")
                list_id = link.get("browser_reference_id")
                if list_name is not None:
                    selected_list = unique(browser_lists, {"Name": list_name}, label + ".list_name")
                    list_id = selected_list["BrowserReferenceId"]
                if list_id is None:
                    raise BulkEditError(f"{label} requires list_name or browser_reference_id")
                prototype_browser = [
                    row for row in browser_rows
                    if row.get("ObjSequenceId") == prototype_row.get("ObjSequenceId")
                ]
                if len(prototype_browser) != 1:
                    prototype_browser = [
                        row for row in browser_rows if row.get("BrowserReferenceId") == _normalize(list_id)
                    ][:1]
                if len(prototype_browser) != 1:
                    raise BulkEditError(f"{label} has no compatible Browser Objects row to clone")
                browser_prototype = prototype_browser[0]
                values.update({
                    "ObjectName": name,
                    "ObjSequenceId": sequence_id,
                    "BrowserReferenceId": _normalize(list_id),
                })
                additions.append({
                    "sheet": _sheet_with_prefix(book, "(22) Browser Objects").name,
                    "clone": {
                        "ObjectName": browser_prototype["ObjectName"],
                        "ObjSequenceId": browser_prototype["ObjSequenceId"],
                    },
                    "values": values,
                })
            elif kind == "modbus_server_status":
                device_match = ({"DeviceName": link["device_name"]} if "device_name" in link
                                else {"DeviceSequenceId": link.get("device_sequence_id")})
                device = unique(modbus_devices, device_match, label + ".device")
                status = link.get("status_control_type")
                if not status:
                    raise BulkEditError(f"{label} requires status_control_type")
                patches.append({
                    "sheet": _sheet_with_prefix(book, "(13) Modbus Server Device - Obj").name,
                    "match": {
                        "DeviceSequenceId": device["DeviceSequenceId"],
                        "StatusControlType": status,
                    },
                    "values": {"ObjSequenceId": sequence_id, **values},
                })
            elif kind == "modbus_scanner_point":
                scanner_id = _normalize(link.get("scanner_sequence_id"))
                scanner = unique(scanner_rows, {"ScannerSequenceId": scanner_id}, label + ".scanner")
                address = link.get("register_address")
                if address is None:
                    raise BulkEditError(f"{label} requires register_address")
                bit_position = link.get("bit_position", 0)
                if any(
                    row.get("PointScannerSequenceId") == scanner["ScannerSequenceId"]
                    and row.get("ModbusRegisterAddress") == _normalize(address)
                    and row.get("ModbusRegisterAddressBitPosition") == _normalize(bit_position)
                    for row in scanner_mapping_rows
                ):
                    raise BulkEditError(
                        f"{label} duplicates scanner {scanner_id} address {address} bit {bit_position}"
                    )
                start = int(scanner["RegisterStartAddr"])
                quantity = int(scanner["RegisterQuantity"])
                address_number = int(address)
                if address_number < start:
                    raise BulkEditError(f"{label} address {address} precedes scanner start {start}")
                required_quantity = address_number - start + 1
                if required_quantity > quantity:
                    patches.append({
                        "sheet": _sheet_with_prefix(book, "(10) Modbus Scanners").name,
                        "match": {"ScannerSequenceId": scanner["ScannerSequenceId"]},
                        "values": {"RegisterQuantity": required_quantity},
                    })
                    scanner["RegisterQuantity"] = required_quantity
                values.update({
                    "PointScannerSequenceId": scanner["ScannerSequenceId"],
                    "ModbusRegisterAddress": address,
                    "ModbusRegisterAddressBitPosition": bit_position,
                    "ObjSequenceId": sequence_id,
                })
                clone = link.get("clone")
                if not clone:
                    candidates = [
                        row for row in scanner_mapping_rows
                        if row.get("PointScannerSequenceId") == scanner["ScannerSequenceId"]
                    ] or scanner_mapping_rows[:1]
                    if not candidates:
                        raise BulkEditError(f"{label} has no scanner-object mapping row to clone")
                    prototype_mapping = candidates[0]
                    clone = {
                        key: prototype_mapping[key]
                        for key in (
                            "PointScannerSequenceId",
                            "ModbusRegisterAddress",
                            "ModbusRegisterAddressBitPosition",
                            "ObjSequenceId",
                        )
                    }
                additions.append({
                    "sheet": _sheet_with_prefix(book, "(14) Modbus Scanner - Obj").name,
                    "clone": clone,
                    "values": values,
                })
                scanner_mapping_rows.append(dict(values))
            elif kind == "physical_io_channel":
                patches.append({
                    "sheet": _sheet_with_prefix(book, "(4) Physical IO Channels").name,
                    "match": {"ModuleId": link.get("module_id"), "Channel": link.get("channel")},
                    "values": {"ObjSequenceId": sequence_id, **values},
                })
            elif kind == "dnp_device_status":
                patches.append({
                    "sheet": _sheet_with_prefix(book, "(11) DNP3 Controlling Station D").name,
                    "match": {
                        "DeviceSequenceId": link.get("device_sequence_id"),
                        "StatusControlType": link.get("status_control_type"),
                    },
                    "values": {"ObjSequenceId": sequence_id, **values},
                })
            elif kind == "dnp_point":
                patches.append({
                    "sheet": _sheet_with_prefix(book, "(12) DNP3 Controlling Station P").name,
                    "match": {"PointSequenceId": link.get("point_sequence_id")},
                    "values": {"ObjSequenceId": sequence_id, **values},
                })
            elif kind == "data_log":
                log_name = str(link.get("log_name", "")).strip()
                if not log_name:
                    raise BulkEditError(f"{label} requires log_name")
                unique(data_logs, {"LogName": log_name}, label + ".log")
                object_values.update({
                    "DataLoggingEnableLogging": "Enabled <1>",
                    "DataLoggingLogFileName": log_name,
                    **values,
                })
            else:
                raise BulkEditError(f"Unsupported relationship kind in {label}: {kind!r}")
            linked.append(kind)
        created.append({
            "name": name,
            "prototype": prototype,
            "requested_sequence_id": sequence_id,
            "relationships": linked,
        })

    written = create_workbook_copy(
        template_path,
        output_path,
        patches,
        additions=additions,
        overwrite=overwrite,
    )
    relationship_validation = inspect_relationships(output_path)
    return {
        **written,
        "objects": created,
        "relationship_validation": relationship_validation,
        "ok": relationship_validation["ok"],
        "next_step": "Apply with apply_remoteconnect_configuration_copy; the DTM remains the semantic authority.",
    }


def configuration_semantics(path: str) -> dict[str, set[tuple]]:
    """Resolve numeric workbook references into stable, name-based identities."""
    _, book = _open(path)
    rows = {
        prefix: _rows_by_prefix(book, prefix)
        for prefix in (
            "(2) Objects", "(3) Physical IO", "(4) Physical IO Channels",
            "(5) DNP3 Controlling Station De", "(6) DNP3 Controlling Station Po",
            "(9) Modbus Server Devices", "(10) Modbus Scanners",
            "(11) DNP3 Controlling Station D", "(12) DNP3 Controlling Station P",
            "(13) Modbus Server Device - Obj", "(14) Modbus Scanner - Obj",
            "(21) Browser Lists", "(22) Browser Objects", "(26) Data Logs",
        )
    }
    objects = {row.get("ObjSequenceId"): row.get("ObjName") for row in rows["(2) Objects"]}
    enabled_objects = {
        (row.get("ObjName"),)
        for row in rows["(2) Objects"]
        if str(row.get("EnableImport", "")).startswith("On")
    }
    browser_lists = {row.get("BrowserReferenceId"): row.get("Name") for row in rows["(21) Browser Lists"]}
    modbus_devices = {row.get("DeviceSequenceId"): row.get("DeviceName") for row in rows["(9) Modbus Server Devices"]}
    scanners = {row.get("ScannerSequenceId"): row for row in rows["(10) Modbus Scanners"]}
    dnp_devices = {row.get("DeviceSequenceId"): row.get("DeviceName") for row in rows["(5) DNP3 Controlling Station De"]}
    dnp_points = {row.get("RemotePointSequenceId"): row for row in rows["(6) DNP3 Controlling Station Po"]}
    return {
        "objects": enabled_objects,
        "browser_links": {
            (row.get("ObjectName"), browser_lists.get(row.get("BrowserReferenceId")))
            for row in rows["(22) Browser Objects"]
        },
        "modbus_scanners": {
            (modbus_devices.get(row.get("DeviceSequenceId")), row.get("RegisterStartAddr"), row.get("RegisterQuantity"))
            for row in rows["(10) Modbus Scanners"]
        },
        "modbus_scanner_links": {
            (
                objects.get(row.get("ObjSequenceId")),
                modbus_devices.get(scanners.get(row.get("PointScannerSequenceId"), {}).get("DeviceSequenceId")),
                row.get("ModbusRegisterAddress"),
                row.get("ModbusRegisterAddressBitPosition"),
            )
            for row in rows["(14) Modbus Scanner - Obj"]
            if row.get("ObjSequenceId", "") != ""
        },
        "modbus_server_links": {
            (objects.get(row.get("ObjSequenceId")), modbus_devices.get(row.get("DeviceSequenceId")), row.get("StatusControlType"))
            for row in rows["(13) Modbus Server Device - Obj"]
            if row.get("ObjSequenceId", "") != ""
        },
        "physical_io_links": {
            (objects.get(row.get("ObjSequenceId")), row.get("ModuleId"), row.get("Channel"))
            for row in rows["(4) Physical IO Channels"]
            if row.get("ObjSequenceId", "") != ""
        },
        "dnp_device_links": {
            (objects.get(row.get("ObjSequenceId")), dnp_devices.get(row.get("DeviceSequenceId")), row.get("StatusControlType"))
            for row in rows["(11) DNP3 Controlling Station D"]
            if row.get("ObjSequenceId", "") != ""
        },
        "dnp_point_links": {
            (
                objects.get(row.get("ObjSequenceId")),
                dnp_devices.get(dnp_points.get(row.get("PointSequenceId"), {}).get("RemoteDeviceId")),
                row.get("RemotePointNumber"),
            )
            for row in rows["(12) DNP3 Controlling Station P"]
            if row.get("ObjSequenceId", "") != ""
        },
        "data_logs": {(row.get("LogName"),) for row in rows["(26) Data Logs"]},
    }


def compare_configuration_semantics(expected_path: str, actual_path: str, *, max_missing: int = 200) -> dict:
    expected = configuration_semantics(expected_path)
    actual = configuration_semantics(actual_path)
    missing = []
    counts = {}
    for category, expected_items in expected.items():
        absent = expected_items - actual[category]
        counts[category] = {"expected": len(expected_items), "actual": len(actual[category]), "missing": len(absent)}
        for identity in sorted(absent, key=repr):
            if len(missing) < max_missing:
                missing.append({"category": category, "identity": list(identity)})
    return {"ok": not missing, "counts": counts, "missing": missing, "missing_truncated": len(missing) >= max_missing}


def compare_configuration_delta(
    before_path: str,
    requested_path: str,
    actual_path: str,
    *,
    max_missing: int = 200,
) -> dict:
    """Verify that entities newly requested by an import survive native re-export.

    A bulk-edit workbook can contain legacy rows which RemoteConnect already omits
    from its own exports. Comparing the whole workbook therefore produces false
    failures.  This comparison treats the source project's native export as the
    baseline and checks every requested addition against the post-import export.
    """
    before = configuration_semantics(before_path)
    requested = configuration_semantics(requested_path)
    actual = configuration_semantics(actual_path)
    missing: list[dict] = []
    missing_total = 0
    counts = {}
    for category, requested_items in requested.items():
        additions = requested_items - before[category]
        absent = additions - actual[category]
        missing_total += len(absent)
        counts[category] = {
            "before": len(before[category]),
            "requested": len(requested_items),
            "requested_additions": len(additions),
            "actual": len(actual[category]),
            "missing_additions": len(absent),
        }
        for identity in sorted(absent, key=repr):
            if len(missing) < max_missing:
                missing.append({"category": category, "identity": list(identity)})
    return {
        "ok": missing_total == 0,
        "counts": counts,
        "missing": missing,
        "missing_total": missing_total,
        "missing_truncated": missing_total > len(missing),
    }


def create_workbook_copy(
    template_path: str,
    output_path: str,
    patches: list[dict] | None = None,
    *,
    additions: list[dict] | None = None,
    overwrite: bool = False,
) -> dict:
    """Patch or clone rows by stable machine fields into a separate XLS copy."""
    source, readable = _open(template_path, formatting=True)
    output = Path(output_path).expanduser().resolve()
    if output.suffix.lower() != ".xls":
        raise BulkEditError("output_path must end in .xls")
    if output == source:
        raise BulkEditError("output_path must differ from template_path")
    if output.exists() and not overwrite:
        raise BulkEditError(f"Output exists (set overwrite=true to replace it): {output}")
    if not patches and not additions:
        raise BulkEditError("At least one patch or addition is required")

    from xlutils.copy import copy

    writable = copy(readable)
    changes = []
    for patch_index, patch in enumerate(patches or []):
        sheet_name = str(patch.get("sheet", ""))
        match = patch.get("match")
        values = patch.get("values")
        if not sheet_name or not isinstance(match, dict) or not match:
            raise BulkEditError(f"patches[{patch_index}] requires sheet and non-empty match")
        if not isinstance(values, dict) or not values:
            raise BulkEditError(f"patches[{patch_index}] requires non-empty values")
        try:
            sheet = readable.sheet_by_name(sheet_name)
        except Exception as exc:
            raise BulkEditError(f"Unknown sheet in patches[{patch_index}]: {sheet_name}") from exc
        fields = [str(sheet.cell_value(1, col)) for col in range(sheet.ncols)]
        columns = {field: col for col, field in enumerate(fields) if field}
        unknown = sorted((set(match) | set(values)) - set(columns))
        if unknown:
            raise BulkEditError(
                f"Unknown fields for sheet '{sheet_name}': {unknown}. "
                f"Use inspect_remoteconnect_bulk_edit_workbook to list fields."
            )
        matches = []
        for row in range(2, sheet.nrows):
            if all(_normalize(sheet.cell_value(row, columns[key])) == _normalize(value)
                   for key, value in match.items()):
                matches.append(row)
        if len(matches) != 1:
            raise BulkEditError(
                f"Patch {patch_index} match selected {len(matches)} rows in '{sheet_name}'; "
                "exactly one is required"
            )
        row = matches[0]
        out_sheet = writable.get_sheet(readable.sheet_names().index(sheet_name))
        for field, new_value in values.items():
            col = columns[field]
            old_value = _normalize(sheet.cell_value(row, col))
            if isinstance(new_value, (dict, list)) or new_value is None:
                raise BulkEditError(
                    f"Value for {sheet_name}.{field} must be a string, number, or boolean"
                )
            out_sheet.write(row, col, new_value)
            changes.append({
                "operation": "update",
                "sheet": sheet_name,
                "row": row + 1,
                "field": field,
                "old": old_value,
                "new": new_value,
            })
    next_rows: dict[str, int] = {}
    for addition_index, addition in enumerate(additions or []):
        sheet_name = str(addition.get("sheet", ""))
        clone = addition.get("clone")
        values = addition.get("values")
        if not sheet_name or not isinstance(clone, dict) or not clone:
            raise BulkEditError(
                f"additions[{addition_index}] requires sheet and non-empty clone match"
            )
        if not isinstance(values, dict) or not values:
            raise BulkEditError(f"additions[{addition_index}] requires non-empty values")
        try:
            sheet_index = readable.sheet_names().index(sheet_name)
            sheet = readable.sheet_by_index(sheet_index)
        except Exception as exc:
            raise BulkEditError(
                f"Unknown sheet in additions[{addition_index}]: {sheet_name}"
            ) from exc
        fields = [str(sheet.cell_value(1, col)) for col in range(sheet.ncols)]
        columns = {field: col for col, field in enumerate(fields) if field}
        unknown = sorted((set(clone) | set(values)) - set(columns))
        if unknown:
            raise BulkEditError(f"Unknown fields for sheet '{sheet_name}': {unknown}")
        clone_rows = [
            row
            for row in range(2, sheet.nrows)
            if all(
                _normalize(sheet.cell_value(row, columns[key])) == _normalize(value)
                for key, value in clone.items()
            )
        ]
        if len(clone_rows) != 1:
            raise BulkEditError(
                f"Addition {addition_index} clone selected {len(clone_rows)} rows in "
                f"'{sheet_name}'; exactly one is required"
            )
        source_row = clone_rows[0]
        output_row = next_rows.get(sheet_name, sheet.nrows)
        next_rows[sheet_name] = output_row + 1
        out_sheet = writable.get_sheet(sheet_index)
        for col in range(sheet.ncols):
            field = fields[col]
            value = values.get(field, sheet.cell_value(source_row, col))
            if isinstance(value, (dict, list)) or value is None:
                raise BulkEditError(
                    f"Value for {sheet_name}.{field or col + 1} must be a string, number, or boolean"
                )
            out_sheet.write(output_row, col, value)
        changes.append({
            "operation": "add",
            "sheet": sheet_name,
            "row": output_row + 1,
            "cloned_from_row": source_row + 1,
            "values": values,
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    writable.save(str(output))
    # Reopen the produced file and verify the RemoteConnect header contract.
    verified = inspect_workbook(str(output), limit=0)
    version = str(verified["metadata"].get("ExportFileVersion", ""))
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise BulkEditError(f"Generated workbook has invalid ExportFileVersion: {version!r}")
    return {
        "template": str(source),
        "output": str(output),
        "changes": changes,
        "change_count": len(changes),
        "verified_reopen": True,
        "metadata": verified["metadata"],
        "next_step": "Import with apply_remoteconnect_configuration_copy; output is withheld if the DTM reports errors.",
    }
