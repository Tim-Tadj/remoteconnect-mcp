"""Check release payload confinement and generated client configuration."""

import importlib.util
import json
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_script("bundle_builder", ROOT / "tools" / "build_client_bundles.py")
configurator = load_script("bundle_configurator", ROOT / "packaging" / "configure.py")


class ClientBundleTests(unittest.TestCase):
    def setUp(self):
        temporary_root = ROOT / ".tools" / "test-tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="client-bundle-", dir=temporary_root)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.bundle = self.directory / "bundle"
        self.bundle.mkdir()
        self.xpdf = self.directory / "installed.xpdf"
        self.xpdf.write_bytes(b"test fixture")
        self.version = "0.20.0rc2"

    def prepare(self, client):
        manifest = {"version": self.version, "client": client}
        (self.bundle / "build-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        plugin = self.bundle / ("codex-plugin" if client in {"codex", "chatgpt"} else "claude-plugin")
        plugin.mkdir()
        template = plugin / ".mcp.json.template"
        template.write_text("immutable template", encoding="utf-8")
        return plugin

    def configure(self, workspace, client="codex"):
        plugin = self.prepare(client)
        with patch.object(configurator, "version", return_value=self.version):
            server = configurator.configure(self.bundle, workspace, self.xpdf)
        return plugin, server

    def test_codex_toml_and_cli_arguments_match_confined_mcp_configuration(self):
        workspace = self.directory / "disposable space"
        plugin, server = self.configure(workspace)
        self.assertEqual(server["env"]["CE_MCP_TOOL_PROFILE"], "offline")
        self.assertEqual(server["env"]["CE_MCP_ENABLE_ONLINE"], "0")
        for key in ("CE_MCP_READ_ROOTS", "CE_MCP_WRITE_ROOTS"):
            self.assertEqual(Path(server["env"][key]), workspace.resolve())
        self.assertEqual(Path(server["command"]), self.bundle.resolve() / "runtime" / "remoteconnect-mcp.exe")
        self.assertEqual(server["args"], [])
        generated = json.loads((plugin / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(generated["mcpServers"]["remoteconnect"], server)
        settings = tomllib.loads((self.bundle / "codex.toml").read_text(encoding="utf-8"))["mcp_servers"]["remoteconnect"]
        for key in ("command", "args", "env"):
            self.assertEqual(settings[key], server[key])
        arguments = json.loads((self.bundle / "codex-args.json").read_text(encoding="utf-8"))
        self.assertEqual(arguments[:2], ["-C", str(workspace.resolve())])
        overrides = arguments[2:]
        self.assertEqual(len(overrides) % 2, 0)
        for option, value in zip(overrides[::2], overrides[1::2]):
            self.assertEqual(option, "-c")
            parsed = tomllib.loads(value)["mcp_servers"]["remoteconnect"]
            for key, entry in parsed.items():
                if key == "env":
                    self.assertEqual(entry, {name: server["env"][name] for name in entry})
                else:
                    self.assertEqual(entry, settings[key])
        self.assertEqual((plugin / ".mcp.json.template").read_text(encoding="utf-8"), "immutable template")

    def test_unicode_workspace_produces_valid_toml(self):
        workspace = self.directory / "disposable \U0001f600"
        _, server = self.configure(workspace)
        settings = tomllib.loads((self.bundle / "codex.toml").read_text(encoding="utf-8"))
        self.assertEqual(settings["mcp_servers"]["remoteconnect"]["env"], server["env"])
        arguments = json.loads((self.bundle / "codex-args.json").read_text(encoding="utf-8"))
        for value in arguments[3::2]:
            tomllib.loads(value)

    def test_claude_configuration_does_not_create_codex_settings(self):
        plugin, server = self.configure(self.directory / "disposable", "claude-code")
        self.assertEqual(json.loads((plugin / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["remoteconnect"], server)
        self.assertFalse((self.bundle / "codex.toml").exists())
        self.assertFalse((self.bundle / "codex-args.json").exists())

    def test_chatgpt_uses_local_codex_plugin_with_absolute_portable_runtime(self):
        plugin, server = self.configure(self.directory / "disposable", "chatgpt")
        self.assertEqual(plugin.name, "codex-plugin")
        self.assertTrue(Path(server["command"]).is_absolute())
        self.assertEqual(server["args"], [])
        self.assertEqual(server["env"]["CE_MCP_WORKSPACE"], server["env"]["CE_MCP_READ_ROOTS"])

    def test_mcpb_template_uses_bundled_binary_and_only_workspace_context_options(self):
        manifest = json.loads((ROOT / "packaging/mcpb/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["server"]["type"], "binary")
        self.assertEqual(manifest["server"]["mcp_config"]["command"], "${__dirname}/runtime/remoteconnect-mcp.exe")
        self.assertEqual(manifest["compatibility"]["platforms"], ["win32"])
        self.assertEqual(set(manifest["user_config"]), {"workspace", "xpdf_context"})
        self.assertEqual(manifest["server"]["mcp_config"]["env"]["CE_MCP_ENABLE_ONLINE"], "0")

    def test_version_mismatch_does_not_create_workspace_or_configuration(self):
        plugin = self.prepare("codex")
        workspace = self.directory / "disposable"
        with patch.object(configurator, "version", return_value="0.19.0"), self.assertRaises(ValueError):
            configurator.configure(self.bundle, workspace, self.xpdf)
        self.assertFalse(workspace.exists())
        self.assertFalse((plugin / ".mcp.json").exists())

    def test_workspace_cannot_grant_access_to_installer_or_runtime_files(self):
        plugin = self.prepare("codex")
        unsafe = [self.bundle, self.bundle.parent, self.bundle / "runtime" / "projects",
                  self.bundle / "codex-plugin" / "projects", self.bundle / "wheelhouse" / "projects"]
        with patch.object(configurator, "version", return_value=self.version):
            for workspace in unsafe:
                with self.subTest(workspace=workspace), self.assertRaises(ValueError):
                    configurator.configure(self.bundle, workspace, self.xpdf)
        self.assertFalse((plugin / ".mcp.json").exists())

    def test_default_bundle_workspace_is_allowed(self):
        workspace = self.bundle / "workspace"
        _, server = self.configure(workspace)
        self.assertEqual(server["env"]["CE_MCP_WRITE_ROOTS"], str(workspace.resolve()))

    def test_network_and_multiple_root_workspace_inputs_are_rejected(self):
        self.prepare("codex")
        with patch.object(configurator, "version", return_value=self.version):
            for workspace in (r"\\server\share", "//server/share", r"D:\one;D:\two", "https://server/projects", r"D:\projects:stream", "${user_config.workspace}"):
                with self.subTest(workspace=workspace), self.assertRaises(ValueError):
                    configurator.configure(self.bundle, workspace, self.xpdf)

    def wheel(self, extra=()):
        path = self.directory / "remoteconnect_mcp-0.20.0rc1-py3-none-any.whl"
        with zipfile.ZipFile(path, "w") as archive:
            for name in ["remoteconnect_mcp/server.py", "remoteconnect_mcp/native/RemoteConnectBridge.cs",
                         "remoteconnect_mcp-0.20.0rc1.dist-info/METADATA", *extra]:
                archive.writestr(name, "fixture")
        return path

    def test_source_and_metadata_wheel_is_accepted(self):
        builder.check_server_wheel(self.wheel())

    def test_wheel_rejects_customer_vendor_and_unexpected_files(self):
        extras = [".tools/customer.PRJ", "remoteconnect_mcp/customer.PRJ", "remoteconnect_mcp/vendor.dll",
                  "remoteconnect_mcp/__pycache__/server.py", "remoteconnect_mcp/../customer.py",
                  "remoteconnect_mcp-0.20.0rc1.dist-info/vendor.dll",
                  "remoteconnect_mcp-0.20.0rc1.dist-info/customer.PRJ"]
        for name in extras:
            with self.subTest(name=name), self.assertRaises(ValueError):
                builder.check_server_wheel(self.wheel([name]))

    def test_wheel_must_contain_native_helper_source(self):
        path = self.directory / "incomplete.whl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("remoteconnect_mcp/server.py", "fixture")
        with self.assertRaises(ValueError):
            builder.check_server_wheel(path)


if __name__ == "__main__":
    unittest.main()
