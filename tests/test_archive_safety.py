"""Archive resource limits and non-destructive cache handling."""

import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from remoteconnect_mcp.logic_archive_bridge import LogicArchiveError, prepare_sta, record_materialized_stu


class ArchiveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.archive = self.root / "project.STA"
        self.xpdf = self.root / "context.xpdf"
        self.xpdf.write_bytes(b"context")
        environment = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)})
        environment.start()
        self.addCleanup(environment.stop)

    def create_archive(self, *, extra=(), apx=b"apx", apd=b"apd"):
        with zipfile.ZipFile(self.archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("BinAppli/Station.apx", apx)
            bundle.writestr("BinAppli/Station.apd", apd)
            for name, value in extra:
                bundle.writestr(name, value)

    def prepare(self, libset_version=""):
        return prepare_sta(str(self.archive), str(self.xpdf), libset_version)

    def materialise(self):
        self.create_archive()
        result = self.prepare()
        working = Path(result["materialized_stu"])
        working.parent.mkdir(parents=True)
        working.write_bytes(b"pristine STU")
        record_materialized_stu(str(working), result["pristine_cache_stu"])
        return result

    def test_sessions_receive_different_working_copies(self):
        first = self.materialise()
        second, third = self.prepare(), self.prepare()
        self.assertTrue(second["cached"])
        self.assertTrue(third["cached"])
        self.assertEqual(len({r["materialized_stu"] for r in (first, second, third)}), 3)
        Path(second["materialized_stu"]).write_bytes(b"session edits")
        self.assertEqual(Path(third["materialized_stu"]).read_bytes(), b"pristine STU")
        self.assertEqual(Path(first["pristine_cache_stu"]).read_bytes(), b"pristine STU")

    def test_mismatched_cache_is_preserved(self):
        first = self.materialise()
        pristine = Path(first["pristine_cache_stu"])
        pristine.write_bytes(b"saved edits from an older session")
        second = self.prepare()
        self.assertFalse(second["cached"])
        self.assertEqual(pristine.read_bytes(), b"saved edits from an older session")
        self.assertEqual(second["preserved_materializations"], [str(pristine)])
        self.assertNotEqual(second["pristine_cache_stu"], str(pristine))

    def test_case_duplicate_payload_is_rejected(self):
        self.create_archive(extra=[("binappli/STATION.APX", b"other payload")])
        with self.assertRaisesRegex(LogicArchiveError, "Duplicate"):
            self.prepare()

    def test_unsafe_entry_name_is_rejected_without_extraction(self):
        self.create_archive(extra=[("../outside.stu", b"hostile")])
        with self.assertRaisesRegex(LogicArchiveError, "Unsafe"):
            self.prepare()
        self.assertFalse((self.root.parent / "outside.stu").exists())

    def test_entry_count_is_limited(self):
        self.create_archive(extra=[("extra.txt", b"extra")])
        with patch("remoteconnect_mcp.logic_archive_bridge.MAX_ARCHIVE_ENTRIES", 2):
            with self.assertRaisesRegex(LogicArchiveError, "more than 2 entries"):
                self.prepare()

    def test_large_compressed_payload_is_rejected_before_read(self):
        self.create_archive(apx=b"A" * 5000)
        with patch("remoteconnect_mcp.logic_archive_bridge.MAX_PAYLOAD_BYTES", 1000), patch.object(
            zipfile.ZipFile, "open", side_effect=AssertionError("decompressed before size validation")
        ):
            with self.assertRaisesRegex(LogicArchiveError, "at most 1000 bytes"):
                self.prepare()

    def test_archive_file_size_is_limited_before_parsing(self):
        self.create_archive()
        with patch("remoteconnect_mcp.logic_archive_bridge.MAX_ARCHIVE_BYTES", 1), patch(
            "remoteconnect_mcp.logic_archive_bridge.zipfile.ZipFile", side_effect=AssertionError("parsed too early")
        ):
            with self.assertRaisesRegex(LogicArchiveError, "size limit"):
                self.prepare()

    def test_empty_payload_is_rejected(self):
        self.create_archive(apd=b"")
        with self.assertRaisesRegex(LogicArchiveError, "non-empty"):
            self.prepare()

    def test_symlink_payload_is_rejected(self):
        with zipfile.ZipFile(self.archive, "w") as bundle:
            symlink = zipfile.ZipInfo("BinAppli/Station.apx")
            symlink.create_system = 3
            symlink.external_attr = 0o120777 << 16
            bundle.writestr(symlink, b"../../outside")
            bundle.writestr("BinAppli/Station.apd", b"apd")
        with self.assertRaisesRegex(LogicArchiveError, "regular file"):
            self.prepare()

    def test_context_and_libset_are_part_of_cache_identity(self):
        first = self.materialise()
        changed_libset = self.prepare("different library")
        self.assertFalse(changed_libset["cached"])
        self.xpdf.write_bytes(b"different context")
        changed_context = self.prepare()
        self.assertFalse(changed_context["cached"])
        self.assertNotEqual(first["pristine_cache_stu"], changed_libset["pristine_cache_stu"])
        self.assertNotEqual(first["pristine_cache_stu"], changed_context["pristine_cache_stu"])

    def test_invalid_manifest_encoding_does_not_delete_stu(self):
        first = self.materialise()
        pristine = Path(first["pristine_cache_stu"])
        pristine.with_suffix(".stu.sha256").write_bytes(b"\xff\xfe")
        second = self.prepare()
        self.assertFalse(second["cached"])
        self.assertEqual(pristine.read_bytes(), b"pristine STU")


if __name__ == "__main__":
    unittest.main()
