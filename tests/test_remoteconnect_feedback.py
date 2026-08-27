import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from remoteconnect_mcp.bulk_edit import (
    BulkEditError,
    _validate_data_log_name,
    compare_configuration_delta,
)
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


class DataLogNameTests(unittest.TestCase):
    def test_remoteconnect_identifier_is_accepted(self):
        _validate_data_log_name("MCP_Demo_Log", "name")

    def test_spaces_are_rejected_before_native_import(self):
        with self.assertRaisesRegex(BulkEditError, "letters, numbers, and underscores"):
            _validate_data_log_name("MCP Demo Log", "name")

    def test_consecutive_underscores_are_rejected(self):
        with self.assertRaisesRegex(BulkEditError, "consecutive underscores"):
            _validate_data_log_name("MCP__Demo", "name")


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

    def test_new_parent_entity_must_survive(self):
        device = ("PumpPLC", "Modbus/TCP <5>", 1, "Serial 1 <1>", "10.0.0.20", 502)
        semantics = {
            "before": {"modbus_devices": set()},
            "requested": {"modbus_devices": {device}},
            "actual": {"modbus_devices": set()},
        }
        with patch(
            "remoteconnect_mcp.bulk_edit.configuration_semantics",
            side_effect=lambda path: semantics[path],
        ):
            result = compare_configuration_delta("before", "requested", "actual")
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing_total"], 1)
        self.assertEqual(result["missing"][0]["category"], "modbus_devices")

    def test_changed_project_setting_must_survive(self):
        disabled = ("RtuProjectSettingsDataLoggingSelected", "Disabled <0>")
        enabled = ("RtuProjectSettingsDataLoggingSelected", "Enabled <1>")
        semantics = {
            "before": {"project_settings": {disabled}},
            "requested": {"project_settings": {enabled}},
            "actual": {"project_settings": {disabled}},
        }
        with patch(
            "remoteconnect_mcp.bulk_edit.configuration_semantics",
            side_effect=lambda path: semantics[path],
        ):
            result = compare_configuration_delta("before", "requested", "actual")
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing"][0]["identity"], list(enabled))


if __name__ == "__main__":
    unittest.main()
