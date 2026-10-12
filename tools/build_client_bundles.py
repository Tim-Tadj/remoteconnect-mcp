"""Build Windows CPython 3.12 x64 client bundles from a clean, committed checkout."""

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_server_wheel(path):
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        for name in names:
            allowed = name.startswith("remoteconnect_mcp/") and (name.endswith(".py") or name == "remoteconnect_mcp/native/RemoteConnectBridge.cs")
            metadata_name = name.split(".dist-info/", 1)[-1]
            allowed |= name.startswith("remoteconnect_mcp-") and ".dist-info/" in name and metadata_name in {"METADATA", "WHEEL", "RECORD", "entry_points.txt", "top_level.txt"}
            if not allowed or ".." in Path(name).parts or "__pycache__" in name:
                raise ValueError(f"Unexpected server wheel content: {name}")
        if "remoteconnect_mcp/native/RemoteConnectBridge.cs" not in names:
            raise ValueError("Server wheel is missing the native helper source")


def build():
    if os.name != "nt" or sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
        raise RuntimeError("Build using Windows x64 CPython 3.12")
    run = lambda arguments, **kwargs: subprocess.run(arguments, cwd=ROOT, check=True, **kwargs)
    if run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout:
        raise RuntimeError("Commit the source changes before building release artefacts")
    commit = run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    plugin_version = re.sub(r"rc(\d+)$", r"-rc.\1", version)
    output = ROOT / "dist" / version
    if output.exists():
        raise FileExistsError(f"Release output already exists: {output}")
    output.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="client-build-", dir=output.parent) as temporary:
        stage = Path(temporary)
        wheels = stage / "wheelhouse"
        wheels.mkdir()
        requirements = stage / "requirements.txt"
        run(["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-header", "--output-file", str(requirements)], stdout=subprocess.DEVNULL)
        run(["uv", "build", "--wheel", "--out-dir", str(wheels)])
        server_wheel, = wheels.glob("remoteconnect_mcp-*.whl")
        check_server_wheel(server_wheel)
        run([sys.executable, "-m", "pip", "download", "--quiet", "--only-binary=:all:", "--require-hashes", "--disable-pip-version-check", "--dest", str(wheels), "--requirement", str(requirements)])
        with requirements.open("a", encoding="utf-8") as stream:
            stream.write(f"\nremoteconnect-mcp=={version} --hash=sha256:{sha256(server_wheel)}\n")
        publication = stage / "release"
        publication.mkdir()
        for client in ("codex", "claude-code"):
            bundle = stage / client
            bundle.mkdir()
            plugin = bundle / ("codex-plugin" if client == "codex" else "claude-plugin")
            shutil.copytree(ROOT / "packaging" / client, plugin)
            shutil.copy2(plugin / "README.md", bundle / "README.md")
            (plugin / "README.md").unlink()
            (plugin / ".mcp.json").rename(plugin / ".mcp.json.template")
            manifest_path = plugin / (".codex-plugin" if client == "codex" else ".claude-plugin") / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["version"] = plugin_version
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            marketplace = json.loads((plugin / "marketplace.json").read_text(encoding="utf-8"))
            for entry in marketplace["plugins"]:
                entry["version"] = plugin_version
            (bundle / ".claude-plugin").mkdir()
            (bundle / ".claude-plugin" / "marketplace.json").write_text(json.dumps(marketplace, indent=2), encoding="utf-8")
            (plugin / "marketplace.json").unlink()
            shutil.copytree(wheels, bundle / "wheelhouse")
            shutil.copy2(requirements, bundle / "requirements.txt")
            for filename in ("Setup.ps1", "configure.py", "Start-Codex.ps1" if client == "codex" else "Start-ClaudeCode.ps1"):
                shutil.copy2(ROOT / "packaging" / filename, bundle / filename)
            data = {"version": version, "plugin_version": plugin_version, "client": client,
                    "target": "Windows CPython 3.12 x64", "git_commit": commit,
                    "files": {p.relative_to(bundle).as_posix(): sha256(p) for p in sorted(bundle.rglob("*")) if p.is_file()}}
            (bundle / "build-manifest.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
            archive = publication / f"remoteconnect-mcp-{client}-{version}-windows-x64.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
                for path in sorted(bundle.rglob("*")):
                    if path.is_file():
                        zip_file.write(path, path.relative_to(bundle).as_posix())
        shutil.copy2(server_wheel, publication / server_wheel.name)
        checksums = "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(publication.iterdir()))
        (publication / "SHA256SUMS.txt").write_text(checksums, encoding="ascii")
        if run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout or run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() != commit:
            raise RuntimeError("Source changed during the build; no release files were published")
        os.rename(publication, output)
    print(output)


if __name__ == "__main__":
    build()
