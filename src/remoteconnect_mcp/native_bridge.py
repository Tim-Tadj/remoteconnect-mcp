"""Programmatic, headless RemoteConnect FDT/DTM bridge.

The installed 32-bit .NET Framework runtime is compiled on demand and invoked
as a captured child process.  It never starts or automates the RemoteConnect UI.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .bulk_edit import BulkEditError, compare_configuration_delta, inspect_workbook
from .remoteconnect import discover_bundle, read_import_report


DEFAULT_INSTALL = Path(r"C:\Program Files (x86)\Schneider Electric\RemoteConnect")


class NativeBridgeError(RuntimeError):
    pass


def _install_path() -> Path:
    return Path(os.environ.get("REMOTECONNECT_HOME", DEFAULT_INSTALL)).resolve()


def _source_path() -> Path:
    return Path(__file__).with_name("native") / "RemoteConnectBridge.cs"


def _references(install: Path) -> list[Path]:
    module = install / "Modules" / "FdtDtmContainerSample"
    framework = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework" / "v4.0.30319"
    return [
        install / "RuntimeFrame.dll",
        install / "Fdt.Datatypes.dll",
        install / "Fdt.Interfaces.dll",
        install / "Fdt.ClrExtension.Interfaces.dll",
        install / "TSF.ToolPattern.Common.dll",
        install / "TSF.CBS.FdtDtm.FdtContainerService.dll",
        install / "TSF.CBS.FdtDtm.FdtContainerService.Interface.dll",
        module / "FdtDtm.Sample.ProjectService.dll",
        module / "FdtDtm.Sample.ProjectService.Interface.dll",
        module / "FdtDtm.Sample.ProjectFileAdapter.dll",
        framework / "WPF" / "WindowsBase.dll",
    ]


def _build_bridge() -> Path:
    if os.name != "nt":
        raise NativeBridgeError("The RemoteConnect native bridge requires Windows")
    install = _install_path()
    source = _source_path()
    compiler = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe"
    refs = _references(install)
    missing = [str(path) for path in [source, compiler, *refs] if not path.is_file()]
    if missing:
        raise NativeBridgeError("RemoteConnect bridge dependency missing: " + ", ".join(missing))

    digest = hashlib.sha256(source.read_bytes())
    for path in refs:
        stat = path.stat()
        digest.update(str(path).encode())
        digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
    build_dir = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "remoteconnect-mcp" / "native" / digest.hexdigest()[:16]
    executable = build_dir / "RemoteConnectBridge.exe"
    if executable.is_file():
        return executable

    build_dir.mkdir(parents=True, exist_ok=True)
    command = [str(compiler), "/nologo", "/target:exe", "/platform:x86", f"/out:{executable}"]
    command.extend(f"/reference:{path}" for path in refs)
    command.append(str(source))
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if completed.returncode:
        raise NativeBridgeError(f"Native bridge compilation failed: {completed.stdout}\n{completed.stderr}".strip())
    app_config = install / "RemoteConnect.exe.config"
    if app_config.is_file():
        shutil.copy2(app_config, Path(str(executable) + ".config"))
    return executable


def _parse_output(stdout: str) -> dict:
    result: dict = {"messages": []}
    dtms = []
    for raw in stdout.splitlines():
        parts = raw.split("\t")
        key, separator, value = parts[0].partition("=")
        if not separator:
            result["messages"].append(raw)
            continue
        if key == "dtm":
            dtms.append({"id": value, "details": parts[1:]})
        elif key in {"dtm_count", "catalog_device_types", "reopened_dtm_count", "log_bytes", "bytes"}:
            try:
                result[key] = int(value)
            except ValueError:
                result[key] = value
        elif key in {"imported", "canceled", "export_canceled", "export_complex_objects"}:
            result[key] = value.lower() == "true"
        else:
            result[key] = value
            if len(parts) > 1:
                result[key + "_details"] = parts[1:]
    result["dtms"] = dtms
    if not result["messages"]:
        result.pop("messages")
    return result


def _run(project: Path, operation: str, workbook: Path, *, timeout: int = 300) -> dict:
    executable = _build_bridge()
    environment = os.environ.copy()
    environment["REMOTECONNECT_HOME"] = str(_install_path())
    completed = subprocess.run(
        [str(executable), str(project), operation, str(workbook)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        env=environment,
    )
    if completed.returncode:
        raise NativeBridgeError(
            f"RemoteConnect native bridge failed ({completed.returncode}): "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    result = _parse_output(completed.stdout)
    result["native_stderr"] = completed.stderr.splitlines()
    result["headless"] = True
    result["ui_automation"] = False
    return result


def _prj_path(path: str) -> Path:
    bundle = discover_bundle(path)
    prj = bundle["files"].get("prj")
    if not prj:
        raise NativeBridgeError(f"No paired .PRJ configuration found for: {path}")
    return Path(prj)


def export_configuration(path: str, output_path: str, *, overwrite: bool = False) -> dict:
    source = _prj_path(path)
    output = Path(output_path).expanduser().resolve()
    if output.suffix.lower() != ".xls":
        raise NativeBridgeError("output_path must end in .xls")
    if output.exists() and not overwrite:
        raise NativeBridgeError(f"Output exists (set overwrite=true to replace it): {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="remoteconnect-export-") as temporary:
        project_copy = Path(temporary) / source.name
        shutil.copy2(source, project_copy)
        result = _run(project_copy, "--export", output)
    if not output.is_file():
        raise NativeBridgeError("The project contains no initialized SCADAPack x70 DTM to export")
    workbook = inspect_workbook(str(output), limit=0)
    return {
        "source": str(source),
        "output": str(output),
        "native": result,
        "workbook": workbook,
        "source_modified": False,
        "ok": output.is_file() and not result.get("export_canceled", False),
    }


def create_configuration_project(
    output_path: str,
    *,
    controller: str = "SCADAPack x70",
    overwrite: bool = False,
) -> dict:
    output = Path(output_path).expanduser().resolve()
    if controller != "SCADAPack x70":
        raise NativeBridgeError("This RemoteConnect version currently supports controller='SCADAPack x70'")
    if output.suffix.lower() != ".prj":
        raise NativeBridgeError("output_path must end in .prj")
    if output.exists() and not overwrite:
        raise NativeBridgeError(f"Output exists (set overwrite=true to replace it): {output}")
    with tempfile.TemporaryDirectory(prefix="remoteconnect-create-") as temporary:
        staging = Path(temporary) / output.name
        native = _run(staging, "--create", Path(controller))
        if native.get("reopened_dtm_count") != 2 or not staging.is_file():
            raise NativeBridgeError("Created project did not reopen with the expected two-DTM topology")
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staging, output)
    return {
        "output": str(output),
        "controller": controller,
        "native": native,
        "created_from_installed_catalog": True,
        "template_used": False,
        "headless": True,
        "ui_automation": False,
        "ok": True,
    }


def import_configuration_copy(
    source_path: str,
    workbook_path: str,
    output_path: str,
    *,
    overwrite: bool = False,
    require_clean: bool = True,
) -> dict:
    source = _prj_path(source_path)
    workbook = Path(workbook_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if not workbook.is_file() or workbook.suffix.lower() != ".xls":
        raise NativeBridgeError(f"RemoteConnect .xls workbook not found: {workbook}")
    if output.suffix.lower() != ".prj":
        raise NativeBridgeError("output_path must end in .prj")
    if output == source:
        raise NativeBridgeError("output_path must differ from the source project")
    if output.exists() and not overwrite:
        raise NativeBridgeError(f"Output exists (set overwrite=true to replace it): {output}")

    inspect_workbook(str(workbook), limit=0)
    with tempfile.TemporaryDirectory(prefix="remoteconnect-import-") as temporary:
        staging = Path(temporary)
        project_copy = staging / source.name
        workbook_copy = staging / workbook.name
        shutil.copy2(source, project_copy)
        shutil.copy2(workbook, workbook_copy)
        baseline_workbook = staging / "baseline-export.xls"
        baseline_native = _run(project_copy, "--export", baseline_workbook)
        inspect_workbook(str(baseline_workbook), limit=0)
        native = _run(project_copy, "--import", workbook_copy)
        report_path = workbook_copy.with_suffix(".import.log.txt")
        report = read_import_report(str(report_path))
        verification: dict = {"attempted": False, "ok": False}
        accepted = bool(native.get("imported")) and not native.get("canceled", False) and report["ok"]
        if accepted:
            verification["attempted"] = True
            verification_workbook = staging / "verification-export.xls"
            try:
                verification_native = _run(project_copy, "--export", verification_workbook)
                verification_schema = inspect_workbook(str(verification_workbook), limit=0)
                semantic = compare_configuration_delta(
                    str(baseline_workbook),
                    str(workbook_copy),
                    str(verification_workbook),
                )
                verification.update({
                    "ok": semantic["ok"],
                    "baseline_native": baseline_native,
                    "native": verification_native,
                    "sheet_count": len(verification_schema["sheets"]),
                    "semantic": semantic,
                })
                if not semantic["ok"]:
                    report["events"].append({
                        "severity": "error",
                        "object": None,
                        "message": "Post-import verification found missing configuration entities or relationships.",
                        "file": str(workbook),
                        "line": None,
                    })
                    report["summary"]["error"] = report["summary"].get("error", 0) + 1
                    report["ok"] = False
            except (NativeBridgeError, BulkEditError, OSError, subprocess.SubprocessError) as exc:
                verification["error"] = str(exc)
                report["events"].append({
                    "severity": "error",
                    "object": None,
                    "message": "Post-import verification export failed: " + str(exc),
                    "file": str(workbook),
                    "line": None,
                })
                report["summary"]["error"] = report["summary"].get("error", 0) + 1
                report["ok"] = False
        clean = accepted and verification["ok"]
        published = clean or not require_clean
        if published:
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(project_copy, output)
    return {
        "source": str(source),
        "workbook": str(workbook),
        "output": str(output) if published else None,
        "published": published,
        "require_clean": require_clean,
        "native": native,
        "verification_export": verification,
        "feedback": report,
        "source_modified": False,
        "ok": clean,
    }
