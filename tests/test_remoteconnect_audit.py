import unittest

from remoteconnect_mcp.audit import (
    compare_configuration_logic,
    merge_configuration_logic_variables,
)


class ConfigurationLogicComparisonTests(unittest.TestCase):
    def test_matching_referenced_object_is_clean(self):
        objects = {("PumpRun", "Digital <1>", "T_SPx70_BOOL <11>", "", "")}
        variables = [{"name": "PumpRun", "type": "T_SPx70_BOOL"}]
        sections = [{"task": "MAST", "section": "Main", "xml": "PumpRun.VALUE := TRUE;"}]
        result = compare_configuration_logic(objects, variables, sections)
        self.assertTrue(result["ok"])
        self.assertEqual(result["matched_object_variables"], 1)
        self.assertEqual(result["referenced_objects"], 1)

    def test_missing_and_mismatched_variables_are_errors(self):
        objects = {
            ("Missing", "Digital <1>", "T_SPx70_BOOL <11>", "", ""),
            ("Wrong", "Analog <0>", "T_SPx70_DINT <4>", 30001, ""),
        }
        variables = [{"name": "Wrong", "type": "T_SPx70_REAL"}]
        result = compare_configuration_logic(objects, variables, [])
        self.assertFalse(result["ok"])
        self.assertEqual(
            {item["kind"] for item in result["errors"]},
            {"missing_logic_variable", "logic_type_mismatch"},
        )

    def test_none_logic_type_is_not_expected_in_stu(self):
        objects = {("System", "Digital <1>", "None <0>", "", "")}
        result = compare_configuration_logic(objects, [], [])
        self.assertTrue(result["ok"])
        self.assertEqual(result["expected_object_variables"], 0)


class ConfigurationVariableMergeTests(unittest.TestCase):
    def test_missing_configuration_variable_is_generated(self):
        merged, summary = merge_configuration_logic_variables(
            [{"name": "PIO_AI1", "type": "T_SPx70_DINT"}],
            [{"name": "Helper", "type": "BOOL"}],
        )
        self.assertEqual([item["name"] for item in merged], ["Helper", "PIO_AI1"])
        self.assertEqual(summary["generated_missing_variables"], 1)

    def test_exact_explicit_match_is_not_duplicated(self):
        merged, summary = merge_configuration_logic_variables(
            [{"name": "Point", "type": "T_SPx70_REAL"}],
            [{"name": "Point", "type": "T_SPx70_REAL", "comment": "User comment"}],
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(summary["explicit_matches"], 1)
        self.assertEqual(merged[0]["comment"], "User comment")

    def test_explicit_type_conflict_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires logic type"):
            merge_configuration_logic_variables(
                [{"name": "Point", "type": "T_SPx70_DINT"}],
                [{"name": "Point", "type": "T_SPx70_REAL"}],
            )


if __name__ == "__main__":
    unittest.main()
