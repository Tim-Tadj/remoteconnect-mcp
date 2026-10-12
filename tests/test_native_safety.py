import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from remoteconnect_mcp.atomic_file import ensure_separate_output, staged_output
from remoteconnect_mcp.bulk_edit import (
    BulkEditError,
    compare_configuration_delta,
    create_workbook_copy,
)
from remoteconnect_mcp.native_bridge import (
    NativeBridgeError,
    _parse_output,
    _install_path,
    _registered_install_paths,
    export_configuration,
    import_configuration_copy,
)
from remoteconnect_mcp.remoteconnect import inspect_project, read_import_report
from remoteconnect_mcp.schema import _load_schema, validate


class AtomicPublicationTests(unittest.TestCase):
    def test_validation_failure_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "project.prj"
            output.write_bytes(b"previous valid project")
            with self.assertRaisesRegex(ValueError, "validation failed"):
                with staged_output(output, overwrite=True) as candidate:
                    candidate.write_bytes(b"invalid project")
                    raise ValueError("validation failed")
            self.assertEqual(output.read_bytes(), b"previous valid project")
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_no_overwrite_remains_exclusive_if_destination_appears(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "project.prj"
            with self.assertRaises(FileExistsError):
                with staged_output(output) as candidate:
                    candidate.write_bytes(b"candidate")
                    output.write_bytes(b"created by another process")
            self.assertEqual(output.read_bytes(), b"created by another process")

    def test_hard_link_to_protected_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "original.prj"
            output = Path(directory) / "alias.prj"
            source.write_bytes(b"protected")
            try:
                os.link(source, output)
            except PermissionError:
                self.skipTest("The Windows sandbox disallows hard-link creation")
            with self.assertRaisesRegex(ValueError, "protected input"):
                ensure_separate_output(output, source)


class SafeXmlTests(unittest.TestCase):
    def test_project_entity_is_rejected_without_reading_local_content(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "secret.txt"
            secret.write_text("do not expose", encoding="utf-8")
            source = Path(directory) / "project.prj"
            xml = f'<!DOCTYPE Project [<!ENTITY x SYSTEM "{secret.as_uri()}">]><Project>&x;</Project>'
            source.write_bytes(xml.encode("utf-16"))
            with self.assertRaisesRegex(ValueError, "DTD declarations"):
                inspect_project(str(source))

    def test_validation_does_not_expand_input_entity(self):
        result = validate('<!DOCTYPE STExchangeFile [<!ENTITY x "expanded">]><STExchangeFile>&x;</STExchangeFile>', ".")
        self.assertFalse(result["valid"])
        self.assertIn("DTD declarations", result["errors"][0])

    def test_schema_include_cannot_escape_selected_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schemas = root / "schemas"
            schemas.mkdir()
            (root / "outside.xsd").write_text('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>')
            xsd = schemas / "STExchangeFile.xsd"
            xsd.write_text('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:include schemaLocation="../outside.xsd"/></xs:schema>')
            _load_schema.cache_clear()
            with self.assertRaises(Exception) as caught:
                _load_schema(str(xsd))
            self.assertIn("schema", str(caught.exception).lower())

    def test_local_schema_include_remains_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            schemas = Path(directory)
            (schemas / "types.xsd").write_text('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="STExchangeFile" type="xs:string"/></xs:schema>')
            (schemas / "STExchangeFile.xsd").write_text('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:include schemaLocation="types.xsd"/></xs:schema>')
            _load_schema.cache_clear()
            self.assertTrue(validate("<STExchangeFile>hello</STExchangeFile>", directory)["valid"])


class NativeOutputTests(unittest.TestCase):
    def test_import_cancellation_and_log_fields_are_parsed(self):
        result = _parse_output("imported=True\tcanceled=True\tworkbook=input.xls\tlog=report.txt\tlog_bytes=42\n")
        self.assertIs(result["imported"], True)
        self.assertIs(result["canceled"], True)
        self.assertEqual(result["log_bytes"], 42)

    def test_unrecognised_boolean_is_not_promoted_to_success(self):
        result = _parse_output("imported=unknown\tcanceled=False")
        self.assertIsNot(result["imported"], True)

    def test_table_error_does_not_consume_the_next_row_error(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.txt"
            report.write_text("Objects Table Validation Error(s) - Row 3\nOther:Invalid data at row [4].", encoding="utf-16")
            parsed = read_import_report(str(report))
        self.assertEqual(parsed["summary"]["error"], 2)


class InstallationDiscoveryTests(unittest.TestCase):
    def test_environment_override_wins_without_reading_registry(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"REMOTECONNECT_HOME": directory}), patch(
            "remoteconnect_mcp.native_bridge._registered_install_paths"
        ) as registry:
            self.assertEqual(_install_path(), Path(directory).resolve())
            registry.assert_not_called()

    def test_registered_custom_directory_is_found(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"REMOTECONNECT_HOME": ""}):
            install = Path(directory) / "custom-install"
            install.mkdir()
            (install / "RuntimeFrame.dll").write_bytes(b"fixture")
            with patch("remoteconnect_mcp.native_bridge.DEFAULT_INSTALL", Path(directory) / "missing"), patch(
                "remoteconnect_mcp.native_bridge._registered_install_paths", return_value=[install, install]
            ):
                self.assertEqual(_install_path(), install)

    def test_multiple_registered_installations_require_override(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"REMOTECONNECT_HOME": ""}):
            installs = [Path(directory) / "one", Path(directory) / "two"]
            for install in installs:
                install.mkdir()
                (install / "RuntimeFrame.dll").write_bytes(b"fixture")
            with patch("remoteconnect_mcp.native_bridge.DEFAULT_INSTALL", Path(directory) / "missing"), patch(
                "remoteconnect_mcp.native_bridge._registered_install_paths", return_value=installs
            ):
                with self.assertRaisesRegex(NativeBridgeError, "REMOTECONNECT_HOME"):
                    _install_path()

    def test_only_exact_registered_product_with_runtime_is_selected(self):
        class Key:
            def __init__(self, name=None):
                self.name = name
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            install = Path(directory)
            (install / "RuntimeFrame.dll").write_bytes(b"fixture")
            entries = {
                "good": {"DisplayName": "RemoteConnect", "InstallLocation": directory},
                "maintenance": {"DisplayName": "RemoteConnect Maintenance Tool", "InstallLocation": directory},
                "missing-runtime": {"DisplayName": "RemoteConnect", "InstallLocation": str(install / "missing")},
            }
            names = list(entries)

            def enum(key, index):
                if index >= len(names):
                    raise OSError()
                return names[index]

            registry = types.SimpleNamespace(
                HKEY_LOCAL_MACHINE=1, HKEY_CURRENT_USER=2,
                KEY_READ=1, KEY_WOW64_32KEY=2, KEY_WOW64_64KEY=4,
                OpenKey=lambda key, name, *args: Key(name if isinstance(key, Key) else None),
                EnumKey=enum,
                QueryValueEx=lambda key, field: (entries[key.name][field], 1),
            )
            with patch.dict("sys.modules", {"winreg": registry}), patch("remoteconnect_mcp.native_bridge.os.name", "nt"), patch("remoteconnect_mcp.native_bridge.Path", type(install)):
                paths = _registered_install_paths()
            self.assertEqual(set(paths), {install})


class NativePublicationTests(unittest.TestCase):
    def _run_import(self, *, native, semantic_ok=False, require_clean=True):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.prj"
            workbook = Path(directory) / "source.xls"
            output = Path(directory) / "output.prj"
            source.write_bytes(b"original")
            workbook.write_bytes(b"requested workbook")
            output.write_bytes(b"existing output")

            def fake_run(project, operation, argument):
                if operation == "--export":
                    argument.write_bytes(b"exported workbook")
                    return {"export_canceled": False}
                project.write_bytes(b"staged partial changes")
                argument.with_suffix(".import.log.txt").write_text("", encoding="utf-16")
                return native

            with patch("remoteconnect_mcp.native_bridge._run", side_effect=fake_run), patch(
                "remoteconnect_mcp.native_bridge.inspect_workbook",
                return_value={"metadata": {"ImportMethod": "Replace all configuration <0>"}, "sheets": []},
            ), patch(
                "remoteconnect_mcp.native_bridge.compare_configuration_delta", return_value={"ok": semantic_ok}
            ):
                result = import_configuration_copy(str(source), str(workbook), str(output), overwrite=True, require_clean=require_clean)
            self.assertEqual(source.read_bytes(), b"original")
            if not result["published"]:
                self.assertEqual(output.read_bytes(), b"existing output")
            return result

    def test_partial_import_is_withheld_even_with_require_clean_false(self):
        result = self._run_import(native={"imported": True, "canceled": False}, require_clean=False)
        self.assertFalse(result["published"])
        self.assertFalse(result["ok"])

    def test_cancelled_import_is_withheld(self):
        result = self._run_import(native={"imported": True, "canceled": True}, semantic_ok=True)
        self.assertFalse(result["published"])
        self.assertFalse(result["verification_export"]["attempted"])

    def test_native_failed_exit_is_withheld_even_with_success_flag(self):
        result = self._run_import(native={"imported": True, "canceled": False, "exit_code": 3}, semantic_ok=True)
        self.assertFalse(result["published"])

    def test_verified_import_is_published(self):
        result = self._run_import(native={"imported": True, "canceled": False}, semantic_ok=True)
        self.assertTrue(result["published"])
        self.assertTrue(result["ok"])

    def test_failed_export_does_not_replace_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.prj"
            output = Path(directory) / "output.xls"
            source.write_bytes(b"original project")
            output.write_bytes(b"previous workbook")
            with patch("remoteconnect_mcp.native_bridge._run", return_value={"export_canceled": True}):
                with self.assertRaises(NativeBridgeError):
                    export_configuration(str(source), str(output), overwrite=True)
            self.assertEqual(output.read_bytes(), b"previous workbook")


class WorkbookVerificationTests(unittest.TestCase):
    template = Path(__file__).resolve().parents[1] / "examples" / "comprehensive_demo" / "RemoteConnect_All_Objects_Demo.xls"

    def test_changed_object_comment_cannot_pass_old_semantic_summary(self):
        import xlrd

        with tempfile.TemporaryDirectory() as directory:
            requested = Path(directory) / "requested.xls"
            sheet = xlrd.open_workbook(str(self.template)).sheet_by_name("(2) Objects")
            fields = sheet.row_values(1)
            name = sheet.cell_value(2, fields.index("ObjName"))
            create_workbook_copy(str(self.template), str(requested), [{
                "sheet": sheet.name, "match": {"ObjName": name}, "values": {"Comment": "Audit comment change"},
            }])
            result = compare_configuration_delta(str(self.template), str(requested), str(self.template))
        self.assertFalse(result["ok"])
        self.assertIn("values:(2) Objects", {entry["category"] for entry in result["missing"]})

    def test_changed_ethernet_address_must_survive(self):
        import xlrd

        with tempfile.TemporaryDirectory() as directory:
            requested = Path(directory) / "requested.xls"
            sheet = xlrd.open_workbook(str(self.template)).sheet_by_name("(20) Ethernet Ports")
            create_workbook_copy(str(self.template), str(requested), [{
                "sheet": sheet.name, "match": {"Port": sheet.cell_value(2, 0)}, "values": {"IpAddress": "192.0.2.11"},
            }])
            result = compare_configuration_delta(str(self.template), str(requested), str(self.template))
        self.assertFalse(result["ok"])
        self.assertIn("values:(20) Ethernet Ports", {entry["category"] for entry in result["missing"]})

    def test_requested_removal_must_survive(self):
        semantics = {"before": {"objects": {("Old",)}}, "requested": {"objects": set()}, "actual": {"objects": {("Old",)}}}
        with patch("remoteconnect_mcp.bulk_edit.configuration_semantics", side_effect=lambda name: semantics[name]):
            result = compare_configuration_delta("before", "requested", "actual")
        self.assertFalse(result["ok"])
        self.assertEqual(result["unapplied_removal_total"], 1)

    def test_invalid_header_does_not_overwrite_existing_workbook(self):
        import xlrd

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.xls"
            output.write_bytes(b"previous workbook")
            sheet = xlrd.open_workbook(str(self.template)).sheet_by_name("(20) Ethernet Ports")
            with patch("remoteconnect_mcp.bulk_edit.inspect_workbook", return_value={"metadata": {"ExportFileVersion": "invalid"}}):
                with self.assertRaisesRegex(BulkEditError, "ExportFileVersion"):
                    create_workbook_copy(str(self.template), str(output), [{
                        "sheet": sheet.name, "match": {"Port": sheet.cell_value(2, 0)}, "values": {"IpAddress": "192.0.2.11"},
                    }], overwrite=True)
            self.assertEqual(output.read_bytes(), b"previous workbook")


if __name__ == "__main__":
    unittest.main()
