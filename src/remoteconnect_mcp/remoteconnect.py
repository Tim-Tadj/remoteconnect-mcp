"""Read-only helpers for RemoteConnect project bundles.

RemoteConnect stores controller configuration in a .PRJ XML file (or .RCZ
archive) and IEC logic in a sibling UnitySoControl .STU/.STA file.  This
module deliberately treats opaque DTM EngineeringData as opaque data.
"""

from __future__ import annotations

import os
import re
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree


REMOTE_EXTENSIONS = (".prj", ".rcz", ".stu", ".sta")
LOGIC_EXTENSIONS = (".stu", ".sta")
DEFAULT_LOG_DIR = Path(os.environ.get("APPDATA", "")) / "Schneider Electric" / "RemoteConnect" / "Logs"


def discover_bundle(path: str) -> dict:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"File not found: {source}")
    if source.suffix.lower() not in REMOTE_EXTENSIONS:
        raise ValueError(
            f"Unsupported RemoteConnect file extension '{source.suffix}'. "
            "Use .prj, .rcz, .stu, or .sta."
        )

    # RemoteConnect uses the same base name with extensions whose case varies.
    siblings = {p.name.lower(): p for p in source.parent.iterdir() if p.is_file()}
    stem = source.stem.lower()
    files: dict[str, str] = {}
    for ext in REMOTE_EXTENSIONS:
        match = siblings.get(stem + ext)
        if match:
            files[ext[1:]] = str(match)

    logic = next((files[e[1:]] for e in LOGIC_EXTENSIONS if e[1:] in files), None)
    return {
        "source": str(source),
        "base_name": source.stem,
        "directory": str(source.parent),
        "files": files,
        "logic_file": logic,
        "complete": "prj" in files and logic is not None,
    }


def inspect_project(path: str) -> dict:
    bundle = discover_bundle(path)
    prj = bundle["files"].get("prj")
    if not prj:
        bundle["configuration"] = {"available": False}
        return bundle

    root = ElementTree.parse(prj).getroot()
    dtms = root.findall(".//DTM")
    records = root.findall(".//InstanceDataRecord")
    bundle["configuration"] = {
        "available": True,
        "format": root.tag,
        "project_id": root.attrib.get("ProjectId", ""),
        "dtm_count": len(dtms),
        "dtm_ids": [item.attrib.get("Id", "") for item in dtms],
        "instance_record_count": len(records),
        "opaque_engineering_data": len(root.findall(".//EngineeringData")),
    }

    rcz = bundle["files"].get("rcz")
    if rcz:
        bundle["archive"] = {
            "path": rcz,
            "zip_compatible": zipfile.is_zipfile(rcz),
            "size": os.path.getsize(rcz),
        }
    return bundle


def inventory_project(path: str) -> dict:
    """Return the safely readable FDT topology and configuration record index.

    RemoteConnect stores record values as opaque vendor serialization.  This
    function deliberately exposes identifiers and record metadata only; it
    never invokes .NET deserialization or interprets/writes payload bytes.
    """
    bundle = discover_bundle(path)
    prj = bundle["files"].get("prj")
    if not prj:
        raise ValueError(f"No paired .PRJ configuration file found for: {path}")
    root = ElementTree.parse(prj).getroot()
    topology_ids = {
        item.attrib.get("Id", "") for item in root.findall("./Topology/TopologyRecord")
    }
    dtms = []
    all_keys: Counter[str] = Counter()
    for index, dtm in enumerate(root.findall("./DTMs/DTM")):
        records = []
        for record in dtm.findall("./InstanceData/InstanceDataRecord"):
            key = record.attrib.get("Key", "")
            all_keys[key] += 1
            records.append({
                "key": key,
                "descriptor": record.attrib.get("Descriptor", ""),
                "encoded_characters": len((record.text or "").strip()),
            })
        dtm_id = dtm.attrib.get("Id", "")
        dtms.append({
            "index": index,
            "id": dtm_id,
            "in_topology": dtm_id in topology_ids,
            "instance_record_count": len(records),
            "records": records,
        })
    return {
        "bundle": bundle,
        "project_id": root.attrib.get("ProjectId", ""),
        "dtms": dtms,
        "topology_ids": sorted(topology_ids),
        "record_groups": [
            {"key": key, "dtm_count": count}
            for key, count in sorted(all_keys.items())
        ],
        "safety": {
            "mode": "read_only_metadata",
            "opaque_payloads_deserialized": False,
            "write_supported": False,
        },
    }


_OBJECT_LINE = re.compile(r"^OBJECT:\s*(.+?)\s*$", re.IGNORECASE)


def _classify_feedback(message: str) -> str:
    low = message.lower()
    if re.search(r"\b(error|failed|invalid|rejected|cannot)\b", low):
        return "error"
    if message.lstrip().startswith("-") or re.search(
        r"\b(warn|automatically|changed because|defaulted)\b", low
    ):
        return "warning"
    if re.search(r"\b(changed|created|deleted|added|removed|updated)\b", low):
        return "change"
    return "info"


def read_feedback(
    log_path: str | None = None,
    *,
    latest: bool = True,
    max_files: int = 20,
) -> dict:
    """Parse RemoteConnect object bulk-edit feedback into structured events."""
    if max_files < 1 or max_files > 200:
        raise ValueError("max_files must be between 1 and 200")
    if log_path:
        source = Path(log_path).expanduser().resolve()
        files = [source]
    else:
        source = DEFAULT_LOG_DIR
        files = sorted(
            source.glob("ObjectBulkEditLog_*.txt"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        files = files[:1] if latest else files[:max_files]
    if not files:
        return {"source": str(source), "files": [], "events": [], "summary": {}}
    for file in files:
        if not file.is_file():
            raise FileNotFoundError(f"Feedback log not found: {file}")

    events = []
    counts: Counter[str] = Counter()
    for file in files:
        current_object = None
        for line_number, raw in enumerate(
            file.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1
        ):
            line = raw.strip()
            if not line:
                continue
            match = _OBJECT_LINE.match(line)
            if match:
                current_object = match.group(1)
                continue
            severity = _classify_feedback(line)
            counts[severity] += 1
            events.append({
                "severity": severity,
                "object": current_object,
                "message": line.lstrip("- "),
                "file": str(file),
                "line": line_number,
            })
    newest = max(files, key=lambda item: item.stat().st_mtime)
    return {
        "source": str(source),
        "files": [str(file) for file in files],
        "latest_timestamp": datetime.fromtimestamp(newest.stat().st_mtime).isoformat(),
        "events": events,
        "summary": dict(sorted(counts.items())),
        "ok": counts["error"] == 0,
    }
