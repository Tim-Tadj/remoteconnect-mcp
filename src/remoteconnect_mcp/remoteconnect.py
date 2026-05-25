"""Read-only helpers for RemoteConnect project bundles.

RemoteConnect stores controller configuration in a .PRJ XML file (or .RCZ
archive) and IEC logic in a sibling UnitySoControl .STU/.STA file.  This
module deliberately treats opaque DTM EngineeringData as opaque data.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from xml.etree import ElementTree


REMOTE_EXTENSIONS = (".prj", ".rcz", ".stu", ".sta")
LOGIC_EXTENSIONS = (".stu", ".sta")


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
