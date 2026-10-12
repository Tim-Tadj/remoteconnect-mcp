"""Portable startup must confine inherited settings before importing the server."""

import builtins
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("portable_launcher", ROOT / "packaging" / "server_launcher.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class PortableLauncherTests(unittest.TestCase):
    def setUp(self):
        temporary_root = ROOT / ".tools" / "test-tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="portable-launcher-", dir=temporary_root)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.installation = self.directory / "bundle"
        self.installation.mkdir()
        self.workspace = self.directory / "disposable space"
        self.environment = {"ProgramData": str(self.directory / "ProgramData"),
                            "LOCALAPPDATA": str(self.directory / "LocalAppData")}

    def xpdf(self, version="16.2"):
        path = Path(self.environment["ProgramData"]) / "Schneider Electric" / "CommonControlExpert" / version / "Xpdf" / "SCBForSCADAPack.xpdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
        return path

    def test_inherited_full_profile_and_broad_roots_are_replaced(self):
        environment = {**self.environment, "CE_MCP_WORKSPACE": str(self.workspace), "CE_MCP_TOOL_PROFILE": "full",
                       "CE_MCP_ENABLE_ONLINE": "1", "CE_MCP_READ_ROOTS": "C:\\", "CE_MCP_WRITE_ROOTS": "C:\\;D:\\"}
        with patch.object(launcher.os, "chdir") as chdir:
            actual = launcher.prepare_environment(self.installation, environment)
        self.assertEqual(actual, self.workspace.resolve())
        self.assertEqual(environment["CE_MCP_TOOL_PROFILE"], "offline")
        self.assertEqual(environment["CE_MCP_ENABLE_ONLINE"], "0")
        for key in ("CE_MCP_READ_ROOTS", "CE_MCP_WRITE_ROOTS", "CE_MCP_WORKSPACE"):
            self.assertEqual(environment[key], str(actual))
        chdir.assert_called_once_with(actual)

    def test_default_workspace_uses_local_app_data_without_requiring_xpdf(self):
        with patch.object(launcher.os, "chdir"):
            actual = launcher.prepare_environment(self.installation, self.environment)
        expected = Path(self.environment["LOCALAPPDATA"]) / "RemoteConnectMCP" / "workspace"
        self.assertEqual(actual, expected.resolve())
        self.assertTrue(actual.is_dir())
        self.assertNotIn("CE_MCP_XPDF_CONTEXT", self.environment)

    def test_installation_ancestors_and_payload_directories_are_rejected_before_writes(self):
        for workspace in (self.installation, self.installation.parent, self.installation / "runtime" / "projects",
                          self.installation / "codex-plugin" / "projects"):
            environment = {**self.environment, "CE_MCP_WORKSPACE": str(workspace)}
            with self.subTest(workspace=workspace), patch.object(launcher.os, "chdir") as chdir, self.assertRaises(ValueError):
                launcher.prepare_environment(self.installation, environment)
            chdir.assert_not_called()
            self.assertNotIn("CE_MCP_READ_ROOTS", environment)

    def test_bundle_workspace_is_allowed(self):
        expected = self.installation / "workspace" / "projects"
        self.assertEqual(launcher.validate_workspace(expected, self.installation), expected.resolve())

    def test_network_placeholders_multiple_roots_and_streams_are_rejected(self):
        for workspace in (r"\\server\share", "//server/share", "https://server/projects", r"D:\one;D:\two",
                          "${user_config.workspace}", r"D:\projects:stream"):
            with self.subTest(workspace=workspace), self.assertRaises(ValueError):
                launcher.validate_workspace(workspace, self.installation)

    def test_xpdf_discovery_accepts_only_one_installed_candidate(self):
        self.assertIsNone(launcher.discover_xpdf(self.environment))
        expected = self.xpdf()
        self.assertEqual(launcher.discover_xpdf(self.environment), expected.resolve())
        self.xpdf("17.0")
        with self.assertRaisesRegex(ValueError, "Multiple.*CE_MCP_XPDF_CONTEXT"):
            launcher.discover_xpdf(self.environment)

    def test_existing_xpdf_selection_is_preserved_without_discovery(self):
        expected = self.xpdf()
        self.xpdf("17.0")
        environment = {**self.environment, "CE_MCP_XPDF_CONTEXT": str(expected)}
        with patch.object(launcher.os, "chdir"):
            launcher.prepare_environment(self.installation, environment)
        self.assertEqual(environment["CE_MCP_XPDF_CONTEXT"], str(expected))

    def test_server_import_occurs_after_environment_confinement(self):
        environment = {**self.environment, "CE_MCP_WORKSPACE": str(self.workspace), "CE_MCP_ENABLE_ONLINE": "1"}
        observed = []
        serve = Mock()
        real_import = builtins.__import__
        def checked_import(name, *args, **kwargs):
            if name == "remoteconnect_mcp.server":
                observed.append((os.environ["CE_MCP_TOOL_PROFILE"], os.environ["CE_MCP_ENABLE_ONLINE"], os.environ["CE_MCP_READ_ROOTS"]))
                return SimpleNamespace(main=serve)
            return real_import(name, *args, **kwargs)
        with patch.dict(os.environ, environment, clear=True), patch.object(builtins, "__import__", side_effect=checked_import), patch.object(launcher.os, "chdir"), patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(self.installation / "runtime" / "remoteconnect-mcp.exe")):
            launcher.main([])
        self.assertEqual(observed, [("offline", "0", str(self.workspace.resolve()))])
        serve.assert_called_once_with()

    @unittest.skipUnless(os.name == "nt", "pywin32 imports require Windows")
    def test_self_check_does_not_start_vendor_runtime_or_server(self):
        import win32com.client
        from remoteconnect_mcp import __version__, native_bridge
        with patch.object(win32com.client, "Dispatch", side_effect=AssertionError("COM activation")), patch.object(native_bridge, "_build_bridge", side_effect=AssertionError("Native runtime")):
            output = StringIO()
            with redirect_stdout(output):
                launcher.main(["--self-check"])
        result = json.loads(output.getvalue())
        self.assertEqual(result["version"], __version__)
        self.assertEqual(result["pywin32_imports"], "passed")
        self.assertFalse(result["vendor_runtime_started"])

    def test_configure_mode_passes_installation_options_without_starting_server(self):
        configure = Mock()
        with patch.dict(sys.modules, {"configure": SimpleNamespace(configure=configure)}), patch.object(launcher.os, "chdir") as chdir:
            launcher.main(["--configure-bundle", str(self.installation), "--workspace", str(self.workspace),
                           "--xpdf-context", "installed.xpdf", "--remoteconnect-home", "vendor"])
        configure.assert_called_once_with(self.installation, str(self.workspace), "installed.xpdf", "vendor")
        chdir.assert_not_called()


if __name__ == "__main__":
    unittest.main()
