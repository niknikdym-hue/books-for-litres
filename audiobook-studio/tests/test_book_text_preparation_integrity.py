from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from book_library import BookLibrary, BookLibraryError, sha256_file
from book_text_preparation import BookTextPreparationService


SOURCE_TEXT = (
    "Глава 1. Начало\n\n"
    "Первое предложение. Второе предложение.\n\n"
    "Глава 2 — Финал\n\n"
    "Заключительный абзац.\n"
)


class PreparedArtifactIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.books = self.root / "books"
        self.source = self.root / "source.txt"
        self.source.write_text(SOURCE_TEXT, encoding="utf-8")
        self.library = BookLibrary(self.books)
        self.library.import_text_book(
            source_file=self.source,
            title="Integrity",
            author="Audiobook Studio Test",
            slug="integrity-book",
        )
        self.service = BookTextPreparationService(
            self.library,
            now=lambda: "2026-08-23T00:00:00+00:00",
        )
        self.asset_root = self.books / "integrity-book"
        self.profile_path = self.books / "integrity-book.json"

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self) -> dict:
        return self.service.prepare("integrity-book")

    def profile(self) -> dict:
        return json.loads(self.profile_path.read_text(encoding="utf-8"))

    def test_ready_profile_seals_exact_structure_and_segment_hashes(self):
        result = self.prepare()
        self.assertEqual(result["preparation_status"], "READY")
        preparation = self.profile()["preparation"]
        self.assertEqual(
            preparation["structure_sha256"],
            sha256_file(self.asset_root / "prepared/structure.json"),
        )
        self.assertEqual(
            preparation["segments_sha256"],
            sha256_file(self.asset_root / "prepared/segments.json"),
        )

    def test_segment_text_tamper_preserving_identity_becomes_stale_and_blocks_execution(self):
        self.prepare()
        path = self.asset_root / "prepared/segments.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        identity = payload["preparation_identity"]
        payload["segments"][0]["text"] += " ПОДМЕНА"
        self.assertEqual(payload["preparation_identity"], identity)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        status = self.service.status("integrity-book")
        self.assertEqual(status["preparation_status"], "STALE")
        self.assertEqual(status["jobs"], [])
        with self.assertRaisesRegex(BookLibraryError, "preparation is STALE"):
            self.library.load_book_for_execution("integrity-book")

    def test_structure_body_tamper_preserving_identity_becomes_stale(self):
        self.prepare()
        path = self.asset_root / "prepared/structure.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        identity = payload["preparation_identity"]
        payload["chapters"][0]["body"] += " ПОДМЕНА"
        self.assertEqual(payload["preparation_identity"], identity)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        status = self.service.status("integrity-book")
        self.assertEqual(status["preparation_status"], "STALE")
        self.assertEqual(status["jobs"], [])

    def test_reprepare_after_corruption_restores_ready_with_current_hashes(self):
        first = self.prepare()
        path = self.asset_root / "prepared/segments.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["segments"][0]["text"] += " ПОДМЕНА"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        corrupted_sha = sha256_file(path)
        self.assertEqual(self.service.status("integrity-book")["preparation_status"], "STALE")

        second = self.prepare()
        preparation = self.profile()["preparation"]
        self.assertEqual(second["preparation_status"], "READY")
        self.assertEqual(second["preparation_revision"], first["preparation_revision"] + 1)
        self.assertEqual(preparation["segments_sha256"], sha256_file(path))
        self.assertNotEqual(preparation["segments_sha256"], corrupted_sha)
        self.assertEqual(
            preparation["structure_sha256"],
            sha256_file(self.asset_root / "prepared/structure.json"),
        )
        execution = self.library.load_book_for_execution("integrity-book")
        self.assertTrue(execution["jobs"]["chapter-ch001"]["segments"])


if __name__ == "__main__":
    unittest.main()
