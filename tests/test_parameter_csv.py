import tempfile
import unittest
from pathlib import Path

from remoteconnect_mcp.parameter_csv import inspect_parameter_csv, create_parameter_csv_copy


class ParameterCSVTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "654321.csv"
        self.output = Path(self.temp.name) / "0.csv"
        self.original = b"(* Site parameters *)\r\noption,1,Pump.VALUE,Enable,1\r\ndi,1,Healthy,Input,10,1\r\n"
        self.source.write_bytes(self.original)

    def patch(self, **changes):
        patch = {"type": "option", "element": 1, "tag": "Pump.VALUE", "expected_values": ["1"], "values": ["-1"]}
        patch.update(changes)
        return patch

    def test_inspection_checks_filename_without_renaming(self):
        result = inspect_parameter_csv(self.source, dnp3_address=0, limit=1)
        self.assertEqual(result["expected_filename"], "0.csv")
        self.assertFalse(result["filename_matches"])
        self.assertEqual(result["next_offset"], 1)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_patch_preserves_comments_endings_and_original(self):
        result = create_parameter_csv_copy(self.source, self.output, [self.patch()])
        self.assertTrue(result["ok"])
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.output.read_bytes(), self.original.replace(b"Enable,1", b"Enable,-1"))
        self.assertIn("+option,1,Pump.VALUE,Enable,-1", result["diff"])

    def test_stale_expected_value_publishes_nothing(self):
        with self.assertRaisesRegex(ValueError, "expected_values"):
            create_parameter_csv_copy(self.source, self.output, [self.patch(expected_values=["2"])])
        self.assertFalse(self.output.exists())

    def test_controller_quoting_and_newlines_not_assumed(self):
        for value in ("x,y", "x\ny", 'x"y'):
            with self.assertRaises(ValueError):
                create_parameter_csv_copy(self.source, self.output, [self.patch(values=[value])])
        self.assertFalse(self.output.exists())

    def test_output_alias_cannot_replace_original(self):
        with self.assertRaises(ValueError):
            create_parameter_csv_copy(self.source, self.source, [self.patch()], overwrite=True)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_existing_quoted_description_is_preserved_exactly(self):
        original = b'option,1,Pump.VALUE,"Pump, north",1\r\n'
        self.source.write_bytes(original)
        create_parameter_csv_copy(self.source, self.output, [self.patch()])
        self.assertEqual(self.output.read_bytes(), original.replace(b',1\r\n', b',-1\r\n'))
        self.assertEqual(inspect_parameter_csv(self.output)["records"][0]["values"], ["-1"])


if __name__ == "__main__":
    unittest.main()
