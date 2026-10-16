"""Offline scanner regressions: synthetic fixtures, never a live school scan."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("scan_school", ROOT / "scripts/scan_school.py")
assert SPEC is not None and SPEC.loader is not None
scanner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scanner)


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qut_scan_tests_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "study"
        self.source.mkdir()
        self.env = mock.patch.dict(os.environ)
        self.env.start()
        for key in ("QUT_STUDY_ROOT", "SCHOOL_DIR", "VAULT_DIR", "NOTES_DIR"):
            os.environ.pop(key, None)
        self.addCleanup(self.env.stop)

    def put(self, name, text="original"):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def scan(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return scanner.scan_and_convert(source=self.source, **kwargs)

    def test_defaults_and_environment_precedence(self):
        self.assertEqual(scanner.resolve_paths()[0], Path.home() / "QUT Study")
        os.environ["QUT_STUDY_ROOT"] = str(self.source)
        self.assertEqual(scanner.resolve_paths(), (self.source, self.source / "notes"))
        os.environ["VAULT_DIR"] = str(self.root / "vault")
        self.assertEqual(scanner.resolve_paths()[1], self.root / "vault/education")
        os.environ["NOTES_DIR"] = str(self.root / "legacy")
        self.assertEqual(scanner.resolve_paths()[1], self.root / "legacy")
        self.assertEqual(scanner.resolve_paths(output=self.root / "explicit")[1], self.root / "explicit")
        self.assertEqual(scanner.resolve_paths(vault=self.root / "explicit-vault")[1], self.root / "explicit-vault/education")

    def test_source_validation_and_output_equal_source(self):
        with self.assertRaises(ValueError):
            scanner.scan_and_convert(source=self.root / "missing")
        with self.assertRaises(ValueError):
            self.scan(output=self.source)
        file = self.put("not-a-dir.txt")
        with self.assertRaises(ValueError):
            scanner.scan_and_convert(source=file)

    def test_default_output_does_not_recurse(self):
        self.put("Unit/a.txt")
        self.assertEqual(self.scan()["processed"], 1)
        self.assertTrue((self.source / "notes/Unit/a.txt.md").is_file())
        self.assertEqual(self.scan()["processed"], 0)
        self.assertFalse((self.source / "notes/notes").exists())

    def test_custom_nested_output_is_pruned(self):
        self.put("a.txt")
        output = self.source / "generated/deep"
        self.scan(output=output)
        self.assertEqual(self.scan(output=output)["processed"], 0)
        self.assertFalse((output / "generated").exists())

    def test_hidden_state_and_symlink_entries_are_skipped(self):
        self.put("valid/a.txt")
        for name in [".hidden/x.txt", "node_modules/x.txt", "__pycache__/x.txt", ".git/x.txt", ".qut-toolkit/x.txt", "state/x.txt", "$temp.txt"]:
            self.put(name)
        self.assertEqual(self.scan()["processed"], 1)

    def test_symlinks_not_followed(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")
        try:
            (self.source / "linked").symlink_to(outside, target_is_directory=True)
            (self.source / "linked.txt").symlink_to(outside / "secret.txt")
        except OSError:
            self.skipTest("Symlink creation unavailable")
        self.assertEqual(self.scan()["processed"], 0)

    def test_missing_subject_fails_without_full_scan(self):
        self.put("Unit/a.txt")
        with self.assertRaises(ValueError):
            self.scan(subject_filter="does-not-exist")
        self.assertFalse((self.source / "notes").exists())

    def test_subject_filters_only_matching_tree(self):
        self.put("Unit/a.txt")
        self.put("Other/b.txt")
        self.assertEqual(self.scan(subject_filter="unit")["processed"], 1)
        self.assertFalse((self.source / "notes/Other").exists())

    def test_ambiguous_subject_fails(self):
        self.put("Unit One/a.txt")
        self.put("Unit Two/b.txt")
        with self.assertRaises(ValueError):
            self.scan(subject_filter="Unit")

    def test_vision_off_by_default(self):
        self.put("image.png", "not-real-image")
        with mock.patch.object(scanner, "extract_image_vision", side_effect=AssertionError("paid call")):
            self.assertEqual(self.scan()["processed"], 1)
        self.assertIn("--vision", (self.source / "notes/image.png.md").read_text())

    def test_explicit_vision_initializes_client(self):
        self.put("image.png")
        fake = mock.Mock()
        with mock.patch.dict(sys.modules, {"anthropic": fake}), mock.patch.object(scanner, "extract_image_vision", return_value="description") as extract:
            self.assertEqual(self.scan(use_vision=True)["processed"], 1)
            fake.Anthropic.assert_called_once_with()
            extract.assert_called_once()

    def test_extension_collisions(self):
        self.put("a.txt")
        self.put("a.pdf")
        with mock.patch.object(scanner, "extract_pdf", return_value="pdf content"):
            self.assertEqual(self.scan()["processed"], 2)
        self.assertTrue((self.source / "notes/a.txt.md").exists())
        self.assertTrue((self.source / "notes/a.pdf.md").exists())

    def test_hashes_not_timestamps_detect_changes(self):
        source = self.put("a.txt")
        self.scan()
        stamp = source.stat().st_mtime
        source.write_text("changed")
        os.utime(source, (stamp, stamp))
        self.assertEqual(self.scan()["processed"], 1)
        self.assertIn("changed", (self.source / "notes/a.txt.md").read_text())

    def test_local_edits_survive_and_remote_change_creates_conflict(self):
        source = self.put("a.txt")
        self.scan()
        note = self.source / "notes/a.txt.md"
        note.write_text("my edits")
        self.assertEqual(self.scan()["processed"], 0)
        source.write_text("remote version")
        result = self.scan()
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(note.read_text(), "my edits")
        conflicts = list(note.parent.glob("a.txt.conflict-*.md"))
        self.assertEqual(len(conflicts), 1)
        self.assertIn("remote version", conflicts[0].read_text())
        self.assertEqual(self.scan()["conflicts"], 0)
        self.assertEqual(len(list(note.parent.glob("a.txt.conflict-*.md"))), 1)

    def test_unmanaged_existing_note_is_never_overwritten(self):
        self.put("a.txt")
        note = self.source / "notes/a.txt.md"
        note.parent.mkdir()
        note.write_text("handwritten")
        self.assertEqual(self.scan()["conflicts"], 1)
        self.assertEqual(note.read_text(), "handwritten")

    def test_extractor_errors_do_not_write_or_mark_success(self):
        self.put("broken.pdf")
        for failure in ["[ERROR reading PDF: broken]", "[No extractable text found in PDF]", ""]:
            with self.subTest(failure=failure), mock.patch.object(scanner, "extract_pdf", return_value=failure):
                self.assertEqual(self.scan()["errors"], 1)
                self.assertFalse((self.source / "notes/broken.pdf.md").exists())
        with mock.patch.object(scanner, "extract_pdf", side_effect=RuntimeError("bad")):
            self.assertEqual(self.scan()["errors"], 1)
        with mock.patch.object(scanner, "extract_pdf", return_value="recovered"):
            self.assertEqual(self.scan()["processed"], 1)

    def test_manifest_records_content_hashes(self):
        self.put("a.txt")
        self.scan()
        data = json.loads((self.source / "notes/.scan_school_manifest.json").read_text())
        record = data["files"]["a.txt"]
        self.assertEqual(len(record["source_hash"]), 64)
        self.assertEqual(len(record["note_hash"]), 64)

    def test_cli_offline_source_output_and_no_vision(self):
        self.put("a.txt")
        for flags in [[], ["--no-vision"]]:
            result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/scan_school.py"), "--source", str(self.source), "--output", str(self.root / "output"), *flags], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Vision : OFF", result.stdout)

    def test_real_corrupt_pdf_is_failure(self):
        self.put("broken.pdf", "this is not a PDF")
        self.assertEqual(self.scan()["errors"], 1)
        self.assertFalse((self.source / "notes/broken.pdf.md").exists())

    def test_vault_output_is_education(self):
        self.put("a.txt")
        vault = self.root / "vault"
        self.assertEqual(self.scan(vault=vault)["processed"], 1)
        self.assertTrue((vault / "education/a.txt.md").exists())
        with self.assertRaises(ValueError):
            self.scan(vault=vault, output=self.root / "other")

    def test_generated_output_from_previous_destination_is_pruned(self):
        self.put("a.txt")
        self.scan(output=self.source / "old-generated")
        self.assertEqual(self.scan()["processed"], 1)
        self.assertFalse((self.source / "notes/old-generated").exists())

    def test_link_predicate_prunes_without_os_symlink_privileges(self):
        self.put("linked/secret.txt")
        self.put("linked.txt")
        self.put("real.txt")
        original = scanner._linked
        with mock.patch.object(scanner, "_linked", side_effect=lambda p: p.name in {"linked", "linked.txt"} or original(p)):
            self.assertEqual(self.scan()["processed"], 1)

    def test_linked_output_target_is_rejected(self):
        self.put("a.txt")
        original = scanner._linked
        with mock.patch.object(scanner, "_linked", side_effect=lambda p: p.name == "notes" or original(p)):
            with self.assertRaises(ValueError):
                self.scan()

    def test_malformed_manifest_is_not_overwritten(self):
        self.put("a.txt")
        manifest = self.source / "notes/.scan_school_manifest.json"
        manifest.parent.mkdir()
        manifest.write_text("invalid json")
        with self.assertRaises(ValueError):
            self.scan()
        self.assertEqual(manifest.read_text(), "invalid json")

    def test_failed_update_preserves_note_and_manifest_record(self):
        source = self.put("a.pdf")
        with mock.patch.object(scanner, "extract_pdf", return_value="valid"):
            self.scan()
        note = self.source / "notes/a.pdf.md"
        manifest = self.source / "notes/.scan_school_manifest.json"
        before_note, before_manifest = note.read_bytes(), manifest.read_bytes()
        source.write_text("new broken source")
        with mock.patch.object(scanner, "extract_pdf", return_value="[ERROR broken]"):
            self.assertEqual(self.scan()["errors"], 1)
        self.assertEqual(note.read_bytes(), before_note)
        self.assertEqual(manifest.read_bytes(), before_manifest)

    def test_cli_errors_exit_one(self):
        self.put("broken.drawio", "<invalid>")
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/scan_school.py"), "--source", str(self.source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_cli_invalid_subject_is_nonzero(self):
        self.put("a.txt")
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/scan_school.py"), "--source", str(self.source), "--subject", "missing"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.source / "notes").exists())


if __name__ == "__main__":
    unittest.main()
