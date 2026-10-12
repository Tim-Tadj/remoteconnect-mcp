"""Validate and unpack the APX/APD payload in a UnitySoControl .STA archive."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import uuid
import zipfile
from pathlib import Path


class LogicArchiveError(RuntimeError):
    pass


# Bound memory use before decompressing vendor input. These intentionally
# generous limits cover large projects while rejecting ZIP resource attacks.
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 4096
MAX_PAYLOAD_BYTES = 128 * 1024 * 1024


def _cache_root() -> Path:
    return (
        Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())).resolve()
        / "remoteconnect-mcp" / "logic-archives"
    )


def _check_cache_path(path: Path) -> None:
    """Reject an existing symlink or junction that escapes our cache root."""
    try:
        path.resolve().relative_to(_cache_root().resolve())
    except ValueError:
        raise LogicArchiveError(f"Archive cache path escapes its root: {path}") from None


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
    directory = _cache_root() / digest.hexdigest()
    return directory / f"{source.stem}.stu"


def record_materialized_stu(path: str, pristine_cache_path: str | None = None) -> None:
    """Keep a pristine cache separate from each session's editable working STU."""
    output = Path(path)
    if pristine_cache_path is not None:
        pristine = Path(pristine_cache_path)
        _check_cache_path(pristine)
        pristine.parent.mkdir(parents=True, exist_ok=True)
        temporary = pristine.with_name(f".{pristine.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copyfile(output, temporary)
            # Do not replace a cache that another process has already published.
            # The working output is still usable if that cache wins the race.
            if pristine.exists():
                return
            # Windows rename refuses to replace an existing destination and is
            # permitted in restricted accounts where hard links are unavailable.
            if os.name == "nt":
                os.rename(temporary, pristine)
            else:
                os.link(temporary, pristine)
        except FileExistsError:
            return
        finally:
            temporary.unlink(missing_ok=True)
        output = pristine
    manifest = output.with_suffix(output.suffix + ".sha256")
    temporary_manifest = manifest.with_name(f".{manifest.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary_manifest.write_text(_file_digest(output), encoding="ascii")
        os.replace(temporary_manifest, manifest)
    finally:
        temporary_manifest.unlink(missing_ok=True)


def _read_payload(bundle: zipfile.ZipFile, item: zipfile.ZipInfo) -> bytes:
    if not 0 < item.file_size <= MAX_PAYLOAD_BYTES:
        raise LogicArchiveError(
            f"Archive payload {item.filename} must be non-empty and at most {MAX_PAYLOAD_BYTES} bytes."
        )
    if item.flag_bits & 1:
        raise LogicArchiveError(f"Encrypted archive payload is unsupported: {item.filename}")
    if item.is_dir() or stat.S_ISLNK(item.external_attr >> 16):
        raise LogicArchiveError(f"Archive payload must be a regular file: {item.filename}")
    with bundle.open(item) as stream:
        payload = stream.read(MAX_PAYLOAD_BYTES + 1)
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise LogicArchiveError(f"Archive payload exceeds the size limit: {item.filename}")
    return payload


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

    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise LogicArchiveError(f"Logic archive exceeds the {MAX_ARCHIVE_BYTES}-byte size limit: {archive}")

    output = _cache_path(archive, xpdf, libset_version)
    _check_cache_path(output)
    manifest = output.with_suffix(output.suffix + ".sha256")
    _check_cache_path(manifest)
    cached = False
    if output.is_file() and output.stat().st_size > 0 and manifest.is_file():
        try:
            cached = manifest.read_text(encoding="ascii").strip() == _file_digest(output)
        except (OSError, UnicodeError):
            cached = False

    # Never delete a mismatched STU. It may contain a user's saved edits from a
    # previous release. Generate into a fresh cache slot instead.
    preserved = []
    if not cached and output.exists():
        preserved.append(str(output))
        output = output.with_name(f"{output.stem}-pristine-{uuid.uuid4().hex}.stu")
    working = output.parent / "working" / uuid.uuid4().hex / f"{archive.stem}.stu"
    _check_cache_path(working)

    result = {
        "source_archive": str(archive),
        "materialized_stu": str(working),
        "pristine_cache_stu": str(output),
        "cached": cached,
        "source_modified": False,
        "headless": True,
        "ui_automation": False,
        "method": "UDE OpenAPX",
    }
    if preserved:
        result["preserved_materializations"] = preserved
    if result["cached"]:
        working.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(output, working)
        return result

    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                raise LogicArchiveError(f"Logic archive has more than {MAX_ARCHIVE_ENTRIES} entries.")
            names: dict[str, zipfile.ZipInfo] = {}
            for entry in entries:
                normalised = entry.filename.replace("\\", "/").casefold()
                parts = normalised.split("/")
                if normalised.startswith("/") or ".." in parts or ":" in normalised:
                    raise LogicArchiveError(f"Unsafe archive entry name: {entry.filename}")
                if normalised in names:
                    raise LogicArchiveError(f"Duplicate archive entry name: {entry.filename}")
                names[normalised] = entry
            apx_name = names.get("binappli/station.apx")
            apd_name = names.get("binappli/station.apd")
            if not apx_name or not apd_name:
                raise LogicArchiveError(
                    f"Invalid .STA archive (BinAppli/Station.apx and Station.apd are required): {archive}"
                )
            result["apx"] = _read_payload(bundle, apx_name)
            result["apd"] = _read_payload(bundle, apd_name)
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as exc:
        if isinstance(exc, LogicArchiveError):
            raise
        raise LogicArchiveError(f"Cannot read .STA archive {archive}: {exc}") from exc
    return result
