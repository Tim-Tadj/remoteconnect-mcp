"""Inspect and patch site runtime parameter files without changing originals."""

from __future__ import annotations

import csv
import difflib
import hashlib
from pathlib import Path

from .atomic_file import ensure_separate_output, staged_output


def _read(path):
    source = Path(path).expanduser().resolve()
    with source.open("rb") as stream:
        data = stream.read(4_000_001)
    if len(data) > 4_000_000:
        raise ValueError("Parameter CSV exceeds the 4 MB inspection limit")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return source, data, data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("Parameter CSV is neither UTF-8 nor Windows-1252")


def _records(text):
    records = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("(*"):
            continue
        fields = next(csv.reader([line], strict=True))
        if len(fields) < 5 or not fields[0].strip() or not fields[1].strip().isdigit():
            raise ValueError(f"Invalid parameter record at line {number}")
        records.append({"line": number, "type": fields[0], "element": int(fields[1]),
                        "tag": fields[2], "description": fields[3], "values": fields[4:]})
    return records


def inspect_parameter_csv(path, *, tag_filter="", offset=0, limit=50, dnp3_address=None):
    if offset < 0 or not 1 <= limit <= 200:
        raise ValueError("offset must be non-negative and limit must be 1..200")
    source, data, text, encoding = _read(path)
    records = _records(text)
    selected = [r for r in records if tag_filter.lower() in r["tag"].lower()]
    result = {"path": str(source), "encoding": encoding, "sha256": hashlib.sha256(data).hexdigest(),
              "record_count": len(records), "matched": len(selected), "offset": offset,
              "records": selected[offset:offset + limit], "next_offset": offset + limit if offset + limit < len(selected) else None,
              "kind": "runtime_parameter_csv", "remoteconnect_xls_import": False}
    if dnp3_address is not None:
        if not 0 <= dnp3_address <= 65535:
            raise ValueError("dnp3_address must be 0..65535")
        result.update(expected_filename=f"{dnp3_address}.csv", filename_matches=source.name == f"{dnp3_address}.csv")
    return result


def create_parameter_csv_copy(source_path, output_path, patches, *, overwrite=False):
    source, original, text, encoding = _read(source_path)
    output = Path(output_path).expanduser().resolve()
    ensure_separate_output(output, source)
    if output.suffix.lower() != ".csv":
        raise ValueError("output_path must end in .csv")
    records = _records(text)
    lines = text.splitlines(keepends=True)
    changed = []
    seen = set()
    for patch in patches:
        identity = (str(patch.get("type", "")), patch.get("element"), str(patch.get("tag", "")))
        if identity in seen:
            raise ValueError("Duplicate parameter patch")
        seen.add(identity)
        matches = [r for r in records if (r["type"], r["element"], r["tag"]) == identity]
        if len(matches) != 1:
            raise ValueError(f"Patch must identify exactly one type/element/tag record: {identity}")
        record = matches[0]
        before = record["values"]
        if patch.get("expected_values") != before:
            raise ValueError(f"expected_values does not match line {record['line']}")
        after = patch.get("values")
        if not isinstance(after, list) or len(after) != len(before) or not all(isinstance(v, str) for v in after):
            raise ValueError("values must be strings with the existing number of fields")
        if any(any(c in v for c in ',\r\n"') for v in after):
            raise ValueError("Values cannot contain commas, quotes or newlines until controller CSV quoting is verified")
        old_line = lines[record["line"] - 1]
        newline = "\r\n" if old_line.endswith("\r\n") else "\n" if old_line.endswith("\n") else ""
        # Preserve descriptions and identifiers byte-for-byte, including existing
        # CSV quoting. New values remain deliberately unquoted until verified.
        quoted = False
        delimiters = 0
        prefix_end = None
        index = 0
        while index < len(old_line):
            character = old_line[index]
            if character == '"':
                if quoted and index + 1 < len(old_line) and old_line[index + 1] == '"':
                    index += 1
                else:
                    quoted = not quoted
            elif character == "," and not quoted:
                delimiters += 1
                if delimiters == 4:
                    prefix_end = index + 1
                    break
            index += 1
        if prefix_end is None:
            raise ValueError("Parameter record has no value-field boundary")
        lines[record["line"] - 1] = old_line[:prefix_end] + ",".join(after) + newline
        changed.append({"line": record["line"], "tag": record["tag"], "before": before, "after": after})
    updated = "".join(lines)
    _records(updated)
    encoded = updated.encode(encoding)
    # Preserve the original BOM policy.
    if encoding == "utf-8-sig" and not original.startswith(b"\xef\xbb\xbf"):
        encoded = updated.encode("utf-8")
    if source.read_bytes() != original:
        raise ValueError("Source changed during editing; retry from a fresh inspection")
    with staged_output(output, overwrite=overwrite) as candidate:
        candidate.write_bytes(encoded)
    return {"ok": True, "published": True, "output_path": str(output), "source_sha256": hashlib.sha256(original).hexdigest(),
            "output_sha256": hashlib.sha256(encoded).hexdigest(), "changes": changed,
            "diff": "".join(difflib.unified_diff(text.splitlines(True), updated.splitlines(True), fromfile=source.name, tofile=output.name)),
            "controller_validation": "not performed"}
