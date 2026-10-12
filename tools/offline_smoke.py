"""Run the comment-only offline integration milestone on disposable project copies.

This script has no controller connection, transfer or live-value operations.
Customer project data and source exports belong in an ignored local output folder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from remoteconnect_mcp.bridge import ControlExpertBridge
from remoteconnect_mcp.logic_workflow import build_logic_copy, section_source
from remoteconnect_mcp.native_bridge import export_configuration
from remoteconnect_mcp.remoteconnect import discover_bundle, inspect_project
from remoteconnect_mcp.parameter_csv import inspect_parameter_csv


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(source_path, output_dir):
    bundle = discover_bundle(source_path)
    source_directory = Path(bundle["directory"])
    output = Path(output_dir).resolve()
    if output.exists():
        raise ValueError("Use a new output directory for every integration run")
    if output.is_relative_to(source_directory):
        raise ValueError("The disposable workspace must be outside the original project directory")
    files = [p for p in source_directory.iterdir() if p.is_file()]
    hashes = {str(p): digest(p) for p in files}
    staged = output / "source"
    reviewed = output / "reviewed"
    references = output / "reference-archives"
    staged.mkdir(parents=True)
    reviewed.mkdir()
    references.mkdir()
    for p in files:
        shutil.copy2(p, staged / p.name)
    staged_bundle = discover_bundle(str(staged / Path(source_path).name))
    report = {"original_hashes": hashes, "hardware_operations": False,
              "inspection": inspect_project(str(staged / Path(source_path).name)),
              "milestone_complete": False, "gui_reopen_verified": False}
    try:
        try:
            report["native_configuration_export"] = export_configuration(str(staged / Path(source_path).name), str(output / "configuration.xls"))
        except Exception as exc:
            report["native_configuration_export"] = {"ok": False, "error": str(exc)}
        for p in staged.glob("*.csv"):
            report.setdefault("parameter_csv", {})[p.name] = inspect_parameter_csv(p, limit=1, dnp3_address=0)
        bridge = ControlExpertBridge()
        try:
            bridge.open_project(staged_bundle["logic_file"])
            structure = bridge.get_project_structure()
            matches = [(t["name"], s["name"]) for t in structure.get("tasks", []) for s in t.get("sections", []) if s["name"].lower() == "parameters"]
            if len(matches) != 1:
                raise ValueError(f"Expected one Parameters section, found {len(matches)}")
            task, section = matches[0]
            source = section_source(bridge.read_section(task, section))
            (output / "Parameters.before.st").write_text(source, encoding="utf-8")
        finally:
            try:
                bridge.close_project(False)
            finally:
                bridge.shutdown()
        comment = "(* Offline MCP audit: comment-only review copy. *)\n"
        target_logic = reviewed / Path(staged_bundle["logic_file"]).with_suffix(".stu").name
        report["logic_copy"] = build_logic_copy(str(staged / Path(source_path).name), str(target_logic), task, section, comment + source)
        (output / "Parameters.diff").write_text(report["logic_copy"]["diff"], encoding="utf-8")
        for p in staged.iterdir():
            if p.is_file() and p.suffix.lower() in {".prj", ".csv"}:
                shutil.copy2(p, reviewed / p.name)
            elif p.is_file() and p.suffix.lower() == ".rcz":
                # RCZ includes the old STA/APX and is not the edited logic bundle.
                shutil.copy2(p, references / p.name)
        configuration_files = [p for p in files if p.suffix.lower() in {".prj", ".rcz", ".csv"}]
        report["configuration_bytes_unchanged"] = all(digest((references if p.suffix.lower() == ".rcz" else reviewed) / p.name) == hashes[str(p)] for p in configuration_files)
        report["rcz_archive_rebuilt"] = False
        report["review_entry_point"] = str(reviewed / Path(source_path).name)
        report["milestone_complete"] = bool(report["logic_copy"]["ok"] and report["configuration_bytes_unchanged"])
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        report["originals_unchanged"] = all(p.is_file() and digest(p) == hashes[str(p)] for p in files)
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report_path": str(output / "report.json"), "milestone_complete": report["milestone_complete"],
                      "originals_unchanged": report["originals_unchanged"], "native_export_ok": report.get("native_configuration_export", {}).get("ok"),
                      "error": report.get("error"), "native_export_error": report.get("native_configuration_export", {}).get("error")}, indent=2), flush=True)
    return 0 if report["milestone_complete"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.source, args.output))
