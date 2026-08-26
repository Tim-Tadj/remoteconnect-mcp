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
