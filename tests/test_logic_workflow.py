import tempfile
import unittest
from pathlib import Path
from xml.sax.saxutils import escape

from remoteconnect_mcp.logic_workflow import build_logic_copy, section_source


class FakeBridge:
    def __init__(self, fail_reopen=False):
        self.source = "value := 1;\n"
        self.fail_reopen = fail_reopen
        self.opens = []

    def open_project(self, path):
        self.opens.append(path)
        if len(self.opens) > 1 and self.fail_reopen:
            self.source = "value := 2;\n"
        return {"opened": path}

    def read_section(self, task, section):
        return {"language": "ST", "xml": "<STExchangeFile><program><STSource>" + escape(self.source) + "</STSource></program></STExchangeFile>"}

    def write_st_logic(self, task, section, source, declare):
        self.source = source
        return {"written": section}

    def build_project(self, full):
        return {"build_state": "built_ok"}

    def save_project(self, path):
        Path(path).write_bytes(b"native-test-project")
        return {"saved": path}

    def close_project(self, save):
        pass

    def shutdown(self):
        pass


class LogicWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "original.stu"
        self.source.write_bytes(b"untouched")
        self.output = Path(self.temp.name) / "changed.stu"

    def test_only_staged_input_is_opened_and_output_is_reopened(self):
        bridge = FakeBridge()
        result = build_logic_copy(self.source, self.output, "MAST", "Parameters", "(* Review *)\nvalue := 1;\n", bridge_factory=lambda: bridge)
        self.assertTrue(result["reopened_source_verified"])
        self.assertNotEqual(Path(bridge.opens[0]), self.source)
        self.assertEqual(len(bridge.opens), 2)
        self.assertEqual(self.source.read_bytes(), b"untouched")
        self.assertIn("+(* Review *)", result["diff"])

    def test_reopen_mismatch_withholds_output(self):
        with self.assertRaisesRegex(ValueError, "differs"):
            build_logic_copy(self.source, self.output, "MAST", "Parameters", "value := 1;\n", bridge_factory=lambda: FakeBridge(True))
        self.assertFalse(self.output.exists())

    def test_original_output_alias_rejected(self):
        with self.assertRaises(ValueError):
            build_logic_copy(self.source, self.source, "MAST", "Parameters", "value := 1;", overwrite=True)

    def test_proprietary_recovery_is_not_accepted_as_source(self):
        with self.assertRaises(ValueError):
            section_source({"language": "ST", "xml": "<recovered>value 1</recovered>"})


if __name__ == "__main__":
    unittest.main()
