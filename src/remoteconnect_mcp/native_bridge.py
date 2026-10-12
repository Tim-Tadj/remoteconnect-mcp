"""Programmatic, headless RemoteConnect FDT/DTM bridge.

The installed 32-bit .NET Framework runtime is compiled on demand and invoked
as a captured child process.  It never starts or automates the RemoteConnect UI.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .atomic_file import ensure_separate_output, publish_copy
from .bulk_edit import BulkEditError, compare_configuration_delta, inspect_workbook
from .remoteconnect import discover_bundle, read_import_report


DEFAULT_INSTALL = Path(r"C:\Program Files (x86)\Schneider Electric\RemoteConnect")


class NativeBridgeError(RuntimeError):
    pass


def _install_path() -> Path:
    override = os.environ.get("REMOTECONNECT_HOME")
    if override:
        return Path(override).expanduser().resolve()
    candidates = _registered_install_paths()
    if (DEFAULT_INSTALL / "RuntimeFrame.dll").is_file():
        candidates.append(DEFAULT_INSTALL)
    available = {path.resolve() for path in candidates if (path / "RuntimeFrame.dll").is_file()}
    if len(available) > 1:
        raise NativeBridgeError("Multiple RemoteConnect installations found; select one using REMOTECONNECT_HOME: " + ", ".join(sorted(map(str, available))))
    if available:
        return available.pop()
    return DEFAULT_INSTALL.resolve()


def _registered_install_paths() -> list[Path]:
    """Read installation metadata, without starting or loading vendor software."""
    if os.name != "nt":
        return []
    import winreg

    candidates = []
    registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, registry_path, 0, winreg.KEY_READ | view) as key:
                    index = 0
                    while True:
                        try:
                            name = winreg.EnumKey(key, index)
                        except OSError:
                            break
                        index += 1
                        try:
                            with winreg.OpenKey(key, name) as entry:
                                display_name = winreg.QueryValueEx(entry, "DisplayName")[0]
                                if str(display_name).strip().casefold() != "remoteconnect":
                                    continue
                                location = winreg.QueryValueEx(entry, "InstallLocation")[0]
                                if location:
                                    candidate = Path(str(location))
                                    if (candidate / "RuntimeFrame.dll").is_file():
                                        candidates.append(candidate)
                        except OSError:
                            continue
            except OSError:
                continue
    return candidates


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


def _build_bridge(build_dir: Path) -> Path:
    if os.name != "nt":
        raise NativeBridgeError("The RemoteConnect native bridge requires Windows")
    install = _install_path()
    source = _source_path()
    compiler = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe"
    refs = _references(install)
    missing = [str(path) for path in [source, compiler, *refs] if not path.is_file()]
    if missing:
        raise NativeBridgeError("RemoteConnect bridge dependency missing: " + ", ".join(missing))

    executable = build_dir / "RemoteConnectBridge.exe"
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
        if "=" not in parts[0]:
            result["messages"].append(raw)
            continue
        key, _, value = parts[0].partition("=")
        if key == "dtm":
            dtms.append({"id": value, "details": parts[1:]})
            continue
        for part in parts:
            field, separator, field_value = part.partition("=")
            if not separator:
                result.setdefault(key + "_details", []).append(part)
            elif field in {"dtm_count", "catalog_device_types", "reopened_dtm_count", "log_bytes", "bytes"}:
                try:
                    result[field] = int(field_value)
                except ValueError:
                    result[field] = field_value
            elif field in {"imported", "canceled", "export_canceled", "export_complex_objects"}:
                result[field] = field_value.lower() == "true" if field_value.lower() in {"true", "false"} else field_value
            else:
                result[field] = field_value
    result["dtms"] = dtms
    if not result["messages"]:
        result.pop("messages")
    return result


def _run(project: Path, operation: str, workbook: Path, *, timeout: int = 300) -> dict:
    if operation not in {"--export", "--import", "--create"}:
        raise NativeBridgeError(f"Unsupported native operation: {operation}")
    environment = os.environ.copy()
    environment["REMOTECONNECT_HOME"] = str(_install_path())
    # Compile inside a fresh process-private directory. Never execute a cached
    # helper which another local process could have replaced between sessions.
    with tempfile.TemporaryDirectory(prefix="remoteconnect-native-") as temporary:
        executable = _build_bridge(Path(temporary))
        completed = subprocess.run(
            [str(executable), str(project), operation, str(workbook)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env=environment,
            cwd=temporary,
        )
    result = _parse_output(completed.stdout)
    if completed.returncode and not (operation == "--import" and "imported" in result):
        raise NativeBridgeError(
            f"RemoteConnect native bridge failed ({completed.returncode}): "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    result["exit_code"] = completed.returncode
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
    try:
        ensure_separate_output(output, source)
    except ValueError as exc:
        raise NativeBridgeError(str(exc)) from exc
    with tempfile.TemporaryDirectory(prefix="remoteconnect-export-") as temporary:
        project_copy = Path(temporary) / source.name
        exported = Path(temporary) / "configuration-export.xls"
        shutil.copy2(source, project_copy)
        result = _run(project_copy, "--export", exported)
        if result.get("export_canceled") is not False or not exported.is_file():
            raise NativeBridgeError("Native configuration export was cancelled or did not produce a workbook")
        workbook = inspect_workbook(str(exported), limit=0)
        publish_copy(exported, output, overwrite=overwrite)
    workbook["path"] = str(output)
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
        publish_copy(staging, output, overwrite=overwrite)
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
    try:
        ensure_separate_output(output, source, workbook)
    except ValueError as exc:
        raise NativeBridgeError(str(exc)) from exc
    if output.exists() and not overwrite:
        raise NativeBridgeError(f"Output exists (set overwrite=true to replace it): {output}")

    requested_schema = inspect_workbook(str(workbook), limit=0)
    import_method = str(requested_schema["metadata"].get("ImportMethod", ""))
    check_removals = import_method.startswith("Replace all configuration")
    with tempfile.TemporaryDirectory(prefix="remoteconnect-import-") as temporary:
        staging = Path(temporary)
        project_copy = staging / "configuration.prj"
        workbook_copy = staging / "requested.xls"
        shutil.copy2(source, project_copy)
        shutil.copy2(workbook, workbook_copy)
        baseline_workbook = staging / "baseline-export.xls"
        baseline_native = _run(project_copy, "--export", baseline_workbook)
        if baseline_native.get("export_canceled") is not False:
            raise NativeBridgeError("Baseline configuration export was cancelled or incomplete")
        inspect_workbook(str(baseline_workbook), limit=0)
        native = _run(project_copy, "--import", workbook_copy)
        report_path = workbook_copy.with_suffix(".import.log.txt")
        report = read_import_report(str(report_path))
        verification: dict = {"attempted": False, "ok": False}
        accepted = native.get("imported") is True and native.get("canceled") is False and native.get("exit_code", 0) == 0 and report["ok"]
        if accepted:
            verification["attempted"] = True
            verification_workbook = staging / "verification-export.xls"
            try:
                verification_native = _run(project_copy, "--export", verification_workbook)
                if verification_native.get("export_canceled") is not False:
                    raise NativeBridgeError("Verification configuration export was cancelled or incomplete")
                verification_schema = inspect_workbook(str(verification_workbook), limit=0)
                semantic = compare_configuration_delta(
                    str(baseline_workbook),
                    str(workbook_copy),
                    str(verification_workbook),
                    check_removals=check_removals,
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
        # A compatibility flag cannot turn a failed or partial import into a
        # publishable project. Validation errors always withhold publication.
        published = clean
        if published:
            output.parent.mkdir(parents=True, exist_ok=True)
            publish_copy(project_copy, output, overwrite=overwrite)
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
