import os
import tempfile
import unittest
from pathlib import Path

from remoteconnect_mcp.tool_policy import ONLINE_TOOLS, ToolPolicy


class ToolPolicyTests(unittest.TestCase):
    def test_online_requires_both_full_profile_and_opt_in(self):
        for profile in ("inspect", "offline", "full"):
            for enabled in ("0", "1"):
                policy = ToolPolicy({"CE_MCP_TOOL_PROFILE": profile, "CE_MCP_ENABLE_ONLINE": enabled})
                for name in ONLINE_TOOLS:
                    self.assertEqual(policy.allows(name), profile == "full" and enabled == "1")

    def test_inspect_cannot_save_through_close(self):
        policy = ToolPolicy({"CE_MCP_TOOL_PROFILE": "inspect"})
        with self.assertRaises(ValueError):
            policy.check_arguments("close_project", {"save": True}, project_path=str(Path.cwd() / "p.stu"))

    def test_save_in_place_checks_write_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = ToolPolicy({}, cwd=directory)
            with self.assertRaisesRegex(ValueError, "WRITE_ROOTS"):
                policy.check_arguments("save_project", {"path": ""}, project_path=str(Path(directory).parent / "original.stu"))

    def test_network_paths_rejected_before_resolving(self):
        policy = ToolPolicy({})
        for path in (r"\\server\share\project.stu", "//server/share/project.stu", "https://example.com/a"):
            with self.assertRaisesRegex(ValueError, "Network paths"):
                policy.check_path(path)

    def test_symlink_outside_root_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "allowed"
            root.mkdir()
            outside = Path(directory) / "outside.stu"
            outside.write_text("data")
            link = root / "project.stu"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("Symlink creation is unavailable")
            with self.assertRaisesRegex(ValueError, "READ_ROOTS"):
                ToolPolicy({}, cwd=root).check_path(link)

    def test_unknown_profile_fails_closed(self):
        with self.assertRaises(ValueError):
            ToolPolicy({"CE_MCP_TOOL_PROFILE": "typo"})

    def test_inline_vendor_documents_reject_external_entities(self):
        policy = ToolPolicy({})
        document = '<!DOCTYPE x [<!ENTITY external SYSTEM "file:///C:/secret.txt">]><x>&external;</x>'
        for field in ("xml_content", "xml", "settings_xso"):
            with self.assertRaisesRegex(ValueError, "DTD"):
                policy.check_arguments("import_xml", {field: document})

    def test_xso_is_validated_as_inline_xml_rather_than_a_path(self):
        ToolPolicy({}).check_arguments("create_remoteconnect_project", {"settings_xso": '<settings><value>1</value></settings>'})


if __name__ == "__main__":
    unittest.main()
