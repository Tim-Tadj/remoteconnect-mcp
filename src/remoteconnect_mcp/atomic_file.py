"""Publish a validated file without leaving a partly written destination."""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path


def ensure_separate_output(output: Path, *sources: Path) -> None:
    """Reject resolved paths and existing hard links to any protected input."""
    for source in sources:
        if output.resolve() == source.resolve() or (
            output.exists() and source.exists() and os.path.samefile(output, source)
        ):
            raise ValueError(f"Output must differ from the protected input: {source}")


@contextmanager
def staged_output(output: Path, *, overwrite: bool = False):
    """Yield a sibling candidate and publish it only after successful validation.

    Windows rename refuses an existing destination and is atomic. On POSIX a
    hard link provides the same exclusive publication. Overwrites use one
    atomic filesystem replacement.
    """
    if output.exists() and not overwrite:
        raise FileExistsError(f"Output exists (set overwrite=true to replace it): {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=".remoteconnect-", suffix=output.suffix, dir=output.parent)
    os.close(handle)
    candidate = Path(name)
    try:
        yield candidate
        if not candidate.is_file() or candidate.stat().st_size == 0:
            raise ValueError("Refusing to publish an empty or missing candidate file")
        if overwrite:
            os.replace(candidate, output)
        elif os.name == "nt":
            os.rename(candidate, output)
        else:
            os.link(candidate, output)
    finally:
        candidate.unlink(missing_ok=True)


def publish_copy(source: Path, output: Path, *, overwrite: bool = False) -> None:
    ensure_separate_output(output, source)
    with staged_output(output, overwrite=overwrite) as candidate:
        shutil.copy2(source, candidate)
