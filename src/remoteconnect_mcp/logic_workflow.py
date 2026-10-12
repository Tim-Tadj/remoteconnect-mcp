"""Source-faithful logic editing on disposable files with reopen checks."""

from __future__ import annotations

import difflib
import hashlib
import shutil
import tempfile
from pathlib import Path

from .atomic_file import ensure_separate_output, staged_output
from .bridge import CEError, ControlExpertBridge
from .remoteconnect import discover_bundle
from .xml_safe import parse_xml_bytes


def section_source(section):
    xml = section.get("xml", "")
    if not xml or section.get("language", "").upper() != "ST":
        raise ValueError("A complete native ST section export is required")
    root = parse_xml_bytes(xml.encode("utf-8"))
    nodes = [n for n in root.iter() if n.tag.rsplit("}", 1)[-1] == "STSource"]
    if len(nodes) != 1:
        raise ValueError("Native section export must contain exactly one STSource")
    return "".join(nodes[0].itertext())


def build_logic_copy(source_path, output_path, task, section, st_source,
                     variables=None, declare=None, overwrite=False, *, bridge_factory=ControlExpertBridge):
    output = Path(output_path).expanduser().resolve()
    if output.suffix.lower() != ".stu":
        raise ValueError("output_path must end in .stu")
    bundle = discover_bundle(source_path)
    logic_path = bundle.get("logic_file")
    if not logic_path:
        raise ValueError("No paired STU or STA logic file was found")
    sources = [Path(value) for value in bundle["files"].values()]
    ensure_separate_output(output, *sources)
    original_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    with tempfile.TemporaryDirectory(prefix="remoteconnect-logic-copy-") as directory:
        work = Path(directory)
        staged_source = work / Path(logic_path).name
        shutil.copy2(logic_path, staged_source)
        saved_path = work / "reviewed.stu"
        logic = bridge_factory()
        try:
            opened = logic.open_project(str(staged_source))
            try:
                before = section_source(logic.read_section(task, section))
            except CEError as exc:
                if f"Section '{section}' not found in task" not in str(exc):
                    raise
                before = ""
            created = []
            for spec in variables or []:
                if not spec.get("name") or not spec.get("type"):
                    raise ValueError("Each variable requires non-empty name and type")
                created.append(logic.create_variable(str(spec["name"]), str(spec["type"]), spec.get("comment"), spec.get("address"), spec.get("initial_value")))
            written = logic.write_st_logic(task, section, st_source, declare or None)
            build = logic.build_project(True)
            if build.get("build_state") != "built_ok" or build.get("error"):
                raise ValueError(f"Full logic build failed: {build}")
            saved = logic.save_project(str(saved_path))
            logic.close_project(False)
            logic.open_project(str(saved_path))
            after = section_source(logic.read_section(task, section))
            # Native editor line endings may differ, but source content must match.
            normalise = lambda value: value.replace("\r\n", "\n").replace("\r", "\n")
            if normalise(after).rstrip("\n") != normalise(st_source).rstrip("\n"):
                raise ValueError("Saved and reopened ST source differs from the requested change")
            reopened_build = logic.build_project(True)
            if reopened_build.get("build_state") != "built_ok" or reopened_build.get("error"):
                raise ValueError(f"Saved and reopened logic failed a full rebuild: {reopened_build}")
            logic.close_project(False)
            if any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest for path, digest in original_hashes.items()):
                raise ValueError("Source bundle changed during validation; no output was published")
            with staged_output(output, overwrite=overwrite) as candidate:
                shutil.copy2(saved_path, candidate)
            return {"ok": True, "published": True, "source_bundle": bundle,
                    "output_path": str(output), "variables": created, "section": written,
                    "build": build, "reopened_build": reopened_build, "reopened_source_verified": True,
                    "source_hashes": original_hashes, "source_unchanged": True,
                    "diff": "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=f"{task}/{section}:before", tofile=f"{task}/{section}:after")),
                    "configuration_modified": False, "configuration_logic_synchronisation": "not verified by this logic-only operation"}
        finally:
            try:
                logic.close_project(False)
            finally:
                logic.shutdown()
