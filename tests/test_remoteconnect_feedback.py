import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from remoteconnect_mcp.bulk_edit import compare_configuration_delta
from remoteconnect_mcp.remoteconnect import read_import_report


class ImportReportTests(unittest.TestCase):
    def test_utf16_table_and_row_errors_are_structured(self):
        content = (
            "BadTag:Invalid Logic Variable Type at row [12].\r\n"
            "Browser Objects Table Validation Error(s) - Row 3\r\n"
            "Unknown Object. Unable to locate an Object with the specified Name and Sequence Id.\r\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "import.log.txt"
            path.write_text(content, encoding="utf-16")
            result = read_import_report(str(path))
        self.assertFalse(result["ok"])
        self.assertEqual(result["summary"], {"error": 2})
        self.assertEqual(result["events"][0]["object"], "BadTag")
        self.assertEqual(result["events"][0]["row"], 12)
        self.assertEqual(result["events"][1]["object"], "Browser Objects")
        self.assertEqual(result["events"][1]["row"], 3)

    def test_empty_report_is_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "import.log.txt"
            path.write_text("", encoding="utf-16")
            result = read_import_report(str(path))
        self.assertTrue(result["ok"])
        self.assertEqual(result["events"], [])


class ConfigurationDeltaTests(unittest.TestCase):
    def test_only_newly_requested_relationships_must_survive(self):
        semantics = {
            "before": {
                "objects": {("Existing",)},
                "modbus_scanner_links": {("Existing", "PLC", 40001, 0)},
            },
            "requested": {
                "objects": {("Existing",), ("Added",)},
                "modbus_scanner_links": {
                    ("Existing", "PLC", 40001, 0),
                    ("Added", "PLC", 40002, 0),
                },
            },
            "actual": {
                "objects": {("Existing",)},
                "modbus_scanner_links": {("Existing", "PLC", 40001, 0)},
            },
        }
        with patch(
            "remoteconnect_mcp.bulk_edit.configuration_semantics",
            side_effect=lambda path: semantics[path],
        ):
            result = compare_configuration_delta("before", "requested", "actual")
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing_total"], 2)
        self.assertIn(
            {"category": "objects", "identity": ["Added"]}, result["missing"]
        )

    def test_preexisting_legacy_omissions_do_not_fail_delta(self):
        semantics = {
            "before": {"objects": {("Existing",), ("Legacy",)}},
            "requested": {"objects": {("Existing",), ("Legacy",)}},
            "actual": {"objects": {("Existing",)}},
        }
        with patch(
            "remoteconnect_mcp.bulk_edit.configuration_semantics",
            side_effect=lambda path: semantics[path],
        ):
            result = compare_configuration_delta("before", "requested", "actual")
        self.assertTrue(result["ok"])
        self.assertEqual(result["missing_total"], 0)


if __name__ == "__main__":
    unittest.main()
