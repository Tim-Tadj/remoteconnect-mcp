"""Validate and unpack the APX/APD payload in a UnitySoControl .STA archive."""

from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
from pathlib import Path


class LogicArchiveError(RuntimeError):
    pass


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_path(source: Path, xpdf: Path, libset_version: str) -> Path:
    digest = hashlib.sha256()
    for path in (source, xpdf):
        digest.update(_file_digest(path).encode("ascii"))
    digest.update(libset_version.encode("utf-8"))
    directory = (
        Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
        / "remoteconnect-mcp"
        / "logic-archives"
        / digest.hexdigest()[:20]
    )
    return directory / f"{source.stem}.stu"


def record_materialized_stu(path: str) -> None:
    """Record the pristine generated STU hash so edited cache files are not reused."""
    output = Path(path)
    output.with_suffix(output.suffix + ".sha256").write_text(
        _file_digest(output), encoding="ascii"
    )


def prepare_sta(
    archive_path: str,
    xpdf_context_path: str,
    libset_version: str = "",
) -> dict:
    """Return cached STU information and, when needed, the archive payload."""
    archive = Path(archive_path).expanduser().resolve()
    xpdf = Path(xpdf_context_path).expanduser().resolve()
    if not archive.is_file() or archive.suffix.lower() != ".sta":
        raise LogicArchiveError(f"Logic archive not found or not .STA: {archive}")
    if not xpdf.is_file():
        raise LogicArchiveError(f"SCADAPack XPDF context file not found: {xpdf}")

    output = _cache_path(archive, xpdf, libset_version)
    manifest = output.with_suffix(output.suffix + ".sha256")
    cached = False
    if output.is_file() and output.stat().st_size > 0 and manifest.is_file():
        try:
            cached = manifest.read_text(encoding="ascii").strip() == _file_digest(output)
        except OSError:
            cached = False
    if not cached:
        # Only internal, content-addressed cache files are removed here. A
        # mismatch means a prior working session edited the materialization or
        # generation was interrupted; recreate it from the immutable archive.
        for stale in (output, manifest):
            try:
                stale.unlink()
            except OSError:
                pass

    result = {
        "source_archive": str(archive),
        "materialized_stu": str(output),
        "cached": cached,
        "source_modified": False,
        "headless": True,
        "ui_automation": False,
        "method": "UDE OpenAPX",
    }
    if result["cached"]:
        return result

    try:
        with zipfile.ZipFile(archive) as bundle:
            names = {name.lower(): name for name in bundle.namelist()}
            apx_name = names.get("binappli/station.apx")
            apd_name = names.get("binappli/station.apd")
            if not apx_name or not apd_name:
                raise LogicArchiveError(
                    f"Invalid .STA archive (BinAppli/Station.apx and Station.apd are required): {archive}"
                )
            result["apx"] = bundle.read(apx_name)
            result["apd"] = bundle.read(apd_name)
    except (OSError, zipfile.BadZipFile) as exc:
        raise LogicArchiveError(f"Cannot read .STA archive {archive}: {exc}") from exc
    return result
