"""Checked native array/member resolution and honest audit uncertainty."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from remoteconnect_mcp.audit import (
    audit_remoteconnect_bundle,
    compare_configuration_logic,
    configuration_logic_variable_specs,
    merge_configuration_logic_variables,
    parse_native_logic_definitions,
)


class AuditPathTests(unittest.TestCase):
    def compare(self, name, variable_type, *, definitions=None, source="", expected="T_SPx70_REAL"):
        return compare_configuration_logic(
            {(name, "Analog <0>", expected, "", "")},
            [{"name": name.split("[")[0].split(".")[0], "type": variable_type}],
            [{"task": "MAST", "section": "Main", "xml": source}],
            type_definitions=definitions,
        )

    def test_native_array_element_matches_terminal_type_and_bounds(self):
        result = self.compare("Totals[1]", "ARRAY[1..3] OF T_SPx70_REAL")
        self.assertTrue(result["ok"])
        self.assertEqual(result["matched_object_variables"], 1)
        self.assertEqual(result["objects"][0]["actual_logic_type"], "T_SPx70_REAL")
        self.assertEqual(result["objects"][0]["resolution_evidence"][0]["bounds"], [(1, 3)])

    def test_array_bounds_and_dimensions_are_checked(self):
        for name in ("Totals[0]", "Totals[4]"):
            with self.subTest(name=name):
                result = self.compare(name, "ARRAY[1..3] OF T_SPx70_REAL")
                self.assertEqual(result["errors"][0]["kind"], "logic_array_index_out_of_bounds")
        result = self.compare("Totals[1]", "ARRAY[1..3,0..2] OF T_SPx70_REAL")
        self.assertEqual(result["errors"][0]["kind"], "logic_array_dimension_mismatch")
        self.assertTrue(self.compare("Totals[1,-1]", "ARRAY[1..3,-1..2] OF T_SPx70_REAL")["ok"])

    def test_correct_base_with_wrong_element_type_does_not_match(self):
        result = self.compare("Totals[1]", "ARRAY[1..3] OF T_SPx70_DINT")
        self.assertEqual(result["errors"][0]["kind"], "logic_type_mismatch")
        self.assertEqual(result["matched_object_variables"], 0)

    def test_unknown_named_array_or_symbolic_bounds_are_unverified(self):
        for declaration in ("TotalsArray", "ARRAY[1..MAX] OF T_SPx70_REAL"):
            with self.subTest(declaration=declaration):
                result = self.compare("Totals[1]", declaration)
                self.assertEqual(result["errors"], [])
                self.assertEqual(result["unverified_object_variables"], 1)
                self.assertFalse(result["verification_complete"])
                self.assertFalse(result["ok"])

    def test_nested_member_array_resolution_uses_exported_definitions(self):
        definitions = {
            "Group": {"complete": True, "members": [{"name": "Sensors", "type": "ARRAY[0..2] OF Sensor"}]},
            "Sensor": {"complete": True, "members": [{"name": "Reading", "type": "T_SPx70_REAL"}]},
        }
        result = self.compare("Pump.Sensors[1].Reading", "Group", definitions=definitions)
        self.assertTrue(result["ok"])
        self.assertEqual(result["objects"][0]["resolved_name"], "Pump.Sensors[1].Reading")
        self.assertEqual(len(result["objects"][0]["resolution_evidence"]), 3)

    def test_unknown_structure_does_not_prove_member_missing(self):
        result = self.compare("Pump.Reading", "ProtectedType")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["unverified_objects"][0]["kind"], "logic_member_type_unverified")

    def test_missing_member_requires_complete_native_definition(self):
        for complete in (True, False):
            with self.subTest(complete=complete):
                result = self.compare("Pump.Reading", "Group", definitions={"Group": {"members": [], "complete": complete}})
                if complete:
                    self.assertEqual(result["errors"][0]["kind"], "missing_logic_member")
                else:
                    self.assertEqual(result["errors"], [])
                    self.assertFalse(result["verification_complete"])

    def test_composite_identifier_casing_is_checked(self):
        result = self.compare("Pump.reading", "Group", definitions={
            "Group": {"members": [{"name": "Reading", "type": "T_SPx70_REAL"}], "complete": True},
        })
        self.assertEqual(result["errors"][0]["kind"], "logic_variable_case_mismatch")
        self.assertEqual(result["errors"][0]["actual_name"], "Pump.Reading")

    def test_dynamic_index_reference_is_reported_as_base_only(self):
        result = self.compare("Totals[1]", "ARRAY[1..3] OF T_SPx70_REAL", source="Totals[index].VALUE := 0.0;")
        self.assertTrue(result["ok"])
        self.assertEqual(result["referenced_objects"], 0)
        self.assertEqual(result["base_referenced_objects"], 1)
        self.assertEqual(result["objects"][0]["reference_evidence"], "base_only")
        literal = self.compare("Totals[1]", "ARRAY[1..3] OF T_SPx70_REAL", source="Totals[1].VALUE := 0.0;")
        self.assertEqual(literal["referenced_objects"], 1)

    def test_comments_and_strings_do_not_count_as_references(self):
        result = self.compare("Totals[1]", "ARRAY[1..3] OF T_SPx70_REAL", source="(* Totals[1] (* nested *) *) Message := 'Totals[1]'; // Totals[1]\n")
        self.assertEqual(result["referenced_objects"], 0)
        self.assertEqual(result["base_referenced_objects"], 0)

    def test_native_type_parser_reads_ddts_and_public_protected_fb_members(self):
        definitions = parse_native_logic_definitions("""<VariablesExchangeFile>
          <DDTSource DDTName="Sensor"><structure><variables name="Reading" typeName="T_SPx70_REAL"/></structure></DDTSource>
          <FBSource nameOfFBType="Pump"><crypted>opaque</crypted><ExternalToolsOnly><outputParameters><variables name="Sensor" typeName="Sensor"/></outputParameters></ExternalToolsOnly></FBSource>
        </VariablesExchangeFile>""")
        self.assertTrue(definitions["sensor"]["complete"])
        self.assertFalse(definitions["pump"]["complete"])
        self.assertEqual(definitions["pump"]["members"], [{"name": "Sensor", "type": "Sensor"}])

    def test_native_type_parser_rejects_ambiguous_duplicate_members(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            parse_native_logic_definitions('<DDTSource DDTName="Sensor"><structure><variables name="Reading" typeName="REAL"/><variables name="reading" typeName="BOOL"/></structure></DDTSource>')

    def test_configuration_generation_refuses_composite_names(self):
        for name in ("Totals[1]", "Pump.Reading"):
            with self.subTest(name=name), patch("remoteconnect_mcp.audit.configuration_semantics", return_value={"objects": {(name, "Analog", "T_SPx70_REAL", "", "")}}):
                with self.assertRaisesRegex(ValueError, "base array or structured declaration"):
                    configuration_logic_variable_specs("configuration.xls")
            with self.assertRaisesRegex(ValueError, "validated base declaration"):
                merge_configuration_logic_variables([{"name": name, "type": "T_SPx70_REAL"}], [])

    def test_explicit_invalid_declaration_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "simple identifier"):
            merge_configuration_logic_variables([], [{"name": "Totals[1]", "type": "T_SPx70_REAL"}])


class AuditSnapshotTests(unittest.TestCase):
    def run_audit(self, directory, *, mutate=False):
        root = Path(directory)
        prj, stu = root / "project.PRJ", root / "project.stu"
        prj.write_bytes(b"configuration")
        stu.write_bytes(b"logic")
        logic = Mock()
        logic.open_project.return_value = {"opened": "staged copy"}
        logic.list_variables.return_value = {"total_variables": 1, "variables": [{"name": "Point", "type": "T_SPx70_REAL"}]}
        logic.export_xml.return_value = {"xml": "<VariablesExchangeFile/>"}
        logic.get_project_structure.return_value = {"tasks": []}

        def build(_):
            if mutate:
                prj.write_bytes(b"concurrent external edit")
            return {"build_state": "built_ok"}

        logic.build_project.side_effect = build
        semantics = {"objects": {("Point", "Analog", "T_SPx70_REAL", "", "")}, "data_logs": [], "modbus_scanners": [], "dnp_points": []}
        with patch("remoteconnect_mcp.audit.ControlExpertBridge", return_value=logic), patch(
            "remoteconnect_mcp.audit.export_configuration", return_value={"ok": True}
        ), patch("remoteconnect_mcp.audit.inspect_workbook", return_value={"sheets": [{}]}), patch(
            "remoteconnect_mcp.audit.inspect_relationships", return_value={"ok": True}
        ), patch("remoteconnect_mcp.audit.configuration_semantics", return_value=semantics):
            return audit_remoteconnect_bundle(str(prj))

    def test_unchanged_snapshot_is_backed_by_both_source_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self.run_audit(directory)
            self.assertTrue(report["ok"])
            self.assertFalse(report["source_modified"])
            self.assertEqual(len(report["source_hashes_before"]), 2)
            self.assertEqual(report["source_hashes_before"], report["source_hashes_after"])

    def test_concurrent_source_change_invalidates_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self.run_audit(directory, mutate=True)
            self.assertFalse(report["ok"])
            self.assertTrue(report["source_modified"])
            self.assertFalse(report["source_hashes_unchanged"])
            self.assertEqual(report["errors"][0]["kind"], "source_changed_during_audit")


if __name__ == "__main__":
    unittest.main()
