import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from remoteconnect_mcp import server
from remoteconnect_mcp.tool_policy import ToolPolicy


class Editor:
    def new_logic_editor_project(self, *args):
        return {"created": True}

    def build_project(self, full):
        return {"build_state": "built_ok"}

    def save_project(self, path):
        Path(path).write_bytes(b"logic")
        return {"saved": path}

    def close_project(self, save):
        return {"closed": True}

    def open_project(self, path):
        return {"opened": path}

    def shutdown(self):
        pass


class ProjectCreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.xpdf = self.root / "context.xpdf"
        self.xpdf.write_text("test")
        self.output = self.root / "new-pair" / "Pair.prj"

    @staticmethod
    def configuration(path):
        Path(path).write_bytes(b"configuration")
        return {"created": True}

    def context(self, editor=Editor):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(server, "policy", ToolPolicy({}, cwd=self.root)))
        stack.enter_context(patch.dict("os.environ", {"CE_MCP_XPDF_CONTEXT": str(self.xpdf)}))
        stack.enter_context(patch.object(server, "create_configuration_project", side_effect=self.configuration))
        stack.enter_context(patch.object(server, "ControlExpertBridge", side_effect=editor))
        return stack

    def test_success_publishes_both_files_in_a_new_directory(self):
        with self.context():
            result = server.create_remoteconnect_project(str(self.output), "SCADAPack47x")
        self.assertTrue(result["atomic_directory_publication"])
        self.assertEqual(self.output.read_bytes(), b"configuration")
        self.assertEqual(self.output.with_suffix(".stu").read_bytes(), b"logic")

    def test_failed_creation_never_closes_global_user_session(self):
        class FailingEditor(Editor):
            def new_logic_editor_project(self, *args):
                raise ValueError("creation failed")
        with self.context(FailingEditor), patch.object(server.ce, "close_project") as close:
            with self.assertRaisesRegex(ValueError, "creation failed"):
                server.create_remoteconnect_project(str(self.output), "SCADAPack47x")
            close.assert_not_called()
        self.assertFalse(self.output.parent.exists())

    def test_publication_failure_leaves_no_half_pair(self):
        with self.context(), patch.object(server.os, "rename", side_effect=OSError("rename failed")):
            with self.assertRaisesRegex(OSError, "rename failed"):
                server.create_remoteconnect_project(str(self.output), "SCADAPack47x")
        self.assertFalse(self.output.parent.exists())

    def test_existing_directory_and_overwrite_are_rejected(self):
        self.output.parent.mkdir()
        original = self.output.with_suffix(".stu")
        original.write_bytes(b"protected")
        with self.context():
            with self.assertRaisesRegex(ValueError, "new output directory"):
                server.create_remoteconnect_project(str(self.output), "SCADAPack47x", overwrite=True)
        self.assertEqual(original.read_bytes(), b"protected")


if __name__ == "__main__":
    unittest.main()
