import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from remoteconnect_mcp.logic_archive_bridge import (
    LogicArchiveError,
    prepare_sta,
    record_materialized_stu,
)


class LogicArchiveTests(unittest.TestCase):
    def _files(self, directory: str):
        root = Path(directory)
        archive = root / "project.STA"
        xpdf = root / "SCBForSCADAPack.xpdf"
        xpdf.write_text("product context", encoding="utf-8")
        return archive, xpdf

    def test_apx_and_apd_are_extracted_without_modifying_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, xpdf = self._files(directory)
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("BinAppli/Station.apx", b"apx payload")
                bundle.writestr("BinAppli/Station.apd", b"apd payload")
            original = archive.read_bytes()
            with patch.dict("os.environ", {"LOCALAPPDATA": directory}):
                result = prepare_sta(str(archive), str(xpdf))
            self.assertFalse(result["cached"])
            self.assertEqual(result["apx"], b"apx payload")
            self.assertEqual(result["apd"], b"apd payload")
            self.assertEqual(result["method"], "UDE OpenAPX")
            self.assertFalse(result["ui_automation"])
            self.assertEqual(archive.read_bytes(), original)

    def test_existing_materialized_stu_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, xpdf = self._files(directory)
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("BinAppli/Station.apx", b"apx")
                bundle.writestr("BinAppli/Station.apd", b"apd")
            with patch.dict("os.environ", {"LOCALAPPDATA": directory}):
                first = prepare_sta(str(archive), str(xpdf))
                Path(first["materialized_stu"]).parent.mkdir(parents=True)
                Path(first["materialized_stu"]).write_bytes(b"stu")
                record_materialized_stu(first["materialized_stu"])
                second = prepare_sta(str(archive), str(xpdf))
            self.assertTrue(second["cached"])
            self.assertNotIn("apx", second)
            self.assertNotIn("apd", second)

    def test_edited_materialization_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, xpdf = self._files(directory)
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("BinAppli/Station.apx", b"apx")
                bundle.writestr("BinAppli/Station.apd", b"apd")
            with patch.dict("os.environ", {"LOCALAPPDATA": directory}):
                first = prepare_sta(str(archive), str(xpdf))
                materialized = Path(first["materialized_stu"])
                materialized.parent.mkdir(parents=True)
                materialized.write_bytes(b"pristine")
                record_materialized_stu(str(materialized))
                materialized.write_bytes(b"edited")
                second = prepare_sta(str(archive), str(xpdf))
            self.assertFalse(second["cached"])
            self.assertFalse(materialized.exists())
            self.assertEqual(second["apx"], b"apx")

    def test_missing_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, xpdf = self._files(directory)
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("props.xml", "<properties />")
            with self.assertRaisesRegex(LogicArchiveError, "Station.apx"):
                prepare_sta(str(archive), str(xpdf))


if __name__ == "__main__":
    unittest.main()
