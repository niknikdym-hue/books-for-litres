from __future__ import annotations

import json
import hashlib
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pronunciation_dictionary import (
    PronunciationDictionary,
    PronunciationDictionaryError,
    apply_auto_pronunciations,
    contextual_review_items,
    load_contextual_registry,
    migrate_book_rules,
    normalize_word,
    validate_dictionary_document,
)


class PronunciationDictionaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = PronunciationDictionary(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _dilon(self):
        return self.store.upsert("Дилон", 1, "Ди́лон")

    def test_ensure_created_is_empty_atomic_private_and_restart_idempotent(self) -> None:
        first = self.store.ensure_created()
        self.assertTrue(first["created"])
        self.assertEqual(first["revision"], 0)
        self.assertEqual(
            json.loads(self.store.path.read_text(encoding="utf-8")),
            {"schema_version": 1, "revision": 0, "entries": []},
        )
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        before = self.store.path.read_bytes()
        second = PronunciationDictionary(self.root).ensure_created()
        self.assertFalse(second["created"])
        self.assertEqual(second["revision"], 0)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(second["sha256"], first["sha256"])

    def test_persistence_permissions_offline_snapshot_and_contract(self) -> None:
        result = self._dilon()
        self.assertTrue(result["changed"])
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        snapshot = PronunciationDictionary(self.root).snapshot()
        self.assertEqual(snapshot["revision"], 1)
        self.assertEqual(snapshot["auto_entry_count"], 1)
        self.assertEqual(snapshot["entries"][0]["normalized_word"], "дилон")
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.path.parent.stat().st_mode & 0o777, 0o700)
        schema = json.loads((ROOT / "contracts/pronunciation-dictionary-v1.schema.json").read_text())
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        validate_dictionary_document({key: snapshot[key] for key in ("schema_version", "revision", "entries")})

    def test_unicode_normalization_case_and_idempotent_upsert(self) -> None:
        first = self._dilon()
        second = self.store.upsert("ДИЛОН", 1, "ДИ́ЛОН")
        self.assertFalse(second["changed"])
        self.assertEqual(second["entry"]["entry_id"], first["entry"]["entry_id"])
        self.assertEqual(normalize_word("Ди\u0301лон"), "дилон")
        self.assertNotEqual(normalize_word("всё"), normalize_word("все"))
        self.assertEqual(self.store.snapshot()["revision"], 1)

    def test_conflict_requires_review_then_owner_selects_preferred(self) -> None:
        first = self.store.upsert("мука", 1, "му́ка")
        conflict = self.store.upsert("МУКА", 2, "МУКА́")
        self.assertTrue(conflict["conflict"])
        self.assertEqual(conflict["entry"]["mode"], "REVIEW_REQUIRED")
        self.assertIsNone(conflict["entry"]["preferred"])
        self.assertEqual(self.store.auto_entries(), [])
        selected = self.store.set_preferred(first["entry"]["entry_id"], 2)
        self.assertEqual(selected["entry"]["mode"], "AUTO")
        self.assertEqual(selected["entry"]["preferred"]["vowel_number"], 2)
        self.assertEqual(len(self.store.auto_entries()), 1)

    def test_known_homograph_is_contextual_from_first_owner_choice(self) -> None:
        registry = load_contextual_registry()
        self.assertEqual(registry["замок"]["source"], "PRONUNCIATION-DICTIONARY-V1")
        result = self.store.upsert("замок", 2, "замо́к")
        self.assertTrue(result["contextual"])
        self.assertTrue(result["conflict"])
        self.assertEqual(result["entry"]["mode"], "REVIEW_REQUIRED")
        self.assertIsNone(result["entry"]["preferred"])
        self.assertEqual(
            [variant["display"] for variant in result["entry"]["variants"]],
            ["за́мок", "замо́к"],
        )
        self.assertEqual(self.store.auto_entries(), [])

    def test_disable_delete_and_missing_variant_fail_closed(self) -> None:
        entry_id = self._dilon()["entry"]["entry_id"]
        disabled = self.store.disable(entry_id)
        self.assertEqual(disabled["entry"]["mode"], "DISABLED")
        self.assertEqual(self.store.auto_entries(), [])
        with self.assertRaises(PronunciationDictionaryError) as captured:
            self.store.set_preferred(entry_id, 9)
        self.assertEqual(captured.exception.code, "variant_not_found")
        deleted = self.store.delete(entry_id)
        self.assertTrue(deleted["deleted"])
        self.assertEqual(self.store.snapshot()["entries"], [])

    def test_auto_application_is_boundary_case_and_existing_acute_aware(self) -> None:
        self._dilon()
        text = "Дилон и ДИЛОН, но недилон и Ди́лонов не меняются."
        applied = apply_auto_pronunciations(text, self.store.auto_entries())
        self.assertEqual(applied, "Ди́лон и ДИ́ЛОН, но недилон и Ди́лонов не меняются.")

    def test_book_and_occurrence_overrides_take_priority(self) -> None:
        global_entry = self.store.upsert("Дилон", 1, "Ди́лон")["entry"]
        text = "Дилон, Дилон и Дилон"
        text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        occurrence = [{
            "scope": "OCCURRENCE", "word": "Дилон", "start": 7, "end": 12,
            "text_sha256": text_sha,
        }]
        self.assertEqual(
            apply_auto_pronunciations(
                text, [global_entry], occurrence, working_copy_sha256=text_sha,
            ),
            "Ди́лон, Дилон и Ди́лон",
        )
        self.assertEqual(
            apply_auto_pronunciations(
                text, [global_entry], occurrence, working_copy_sha256="0" * 64,
            ),
            "Ди́лон, Ди́лон и Ди́лон",
        )
        book = [{"scope": "BOOK", "word": "ДИЛОН", "vowel_number": 2}]
        self.assertEqual(apply_auto_pronunciations(text, [global_entry], book), text)

    def test_invalid_display_corrupt_and_higher_schema_are_not_overwritten(self) -> None:
        with self.assertRaises(PronunciationDictionaryError) as captured:
            self.store.upsert("замок", 1, "замо́к")
        self.assertEqual(captured.exception.code, "invalid_display")
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        corrupt = b"{not-json\n"
        self.store.path.write_bytes(corrupt)
        with self.assertRaises(PronunciationDictionaryError):
            self._dilon()
        self.assertEqual(self.store.path.read_bytes(), corrupt)
        higher = json.dumps({
            "schema_version": 2, "revision": 7, "entries": [], "future_field": True,
        }).encode()
        self.store.path.write_bytes(higher)
        with self.assertRaises(PronunciationDictionaryError) as captured:
            self._dilon()
        self.assertEqual(captured.exception.code, "schema_upgrade_required")
        self.assertEqual(self.store.path.read_bytes(), higher)

    def test_symlink_components_store_and_lock_fail_closed(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / "settings").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(PronunciationDictionaryError) as captured:
            self._dilon()
        self.assertEqual(captured.exception.code, "unsafe_dictionary_path")
        self.assertEqual(list(outside.iterdir()), [])

        other_root = self.root / "safe"
        other_root.mkdir()
        other = PronunciationDictionary(other_root)
        other.path.parent.mkdir(parents=True)
        target = other_root / "target"
        target.write_text("untouched")
        other.lock_path.symlink_to(target)
        with self.assertRaises(PronunciationDictionaryError):
            other.upsert("Дилон", 1, "Ди́лон")
        self.assertEqual(target.read_text(), "untouched")

    def test_atomic_fsync_replace_and_advisory_lock_cross_process(self) -> None:
        real_fsync = os.fsync
        real_replace = os.replace
        fsyncs: list[int] = []
        replacements: list[tuple[str, str]] = []
        with mock.patch("pronunciation_dictionary.os.fsync", side_effect=lambda fd: (fsyncs.append(fd), real_fsync(fd))[1]), \
             mock.patch("pronunciation_dictionary.os.replace", side_effect=lambda a, b: (replacements.append((str(a), str(b))), real_replace(a, b))[1]):
            self._dilon()
        self.assertGreaterEqual(len(fsyncs), 2)
        self.assertEqual(len(replacements), 1)
        self.assertEqual(Path(replacements[0][1]), self.store.path)

        code = (
            "from pronunciation_dictionary import PronunciationDictionary; import os,time; "
            "time.sleep(float(os.environ['DELAY'])); "
            "PronunciationDictionary(os.environ['ROOT']).upsert(os.environ['WORD'],1,os.environ['DISPLAY'])"
        )
        environment = dict(os.environ, PYTHONPATH=str(ROOT), ROOT=str(self.root / "parallel"))
        (self.root / "parallel").mkdir()
        processes = []
        for word, display, delay in (("Дилон", "Ди́лон", "0"), ("Лера", "Ле́ра", "0.01")):
            processes.append(subprocess.Popen(
                [sys.executable, "-c", code],
                env=dict(environment, WORD=word, DISPLAY=display, DELAY=delay),
            ))
        self.assertEqual([process.wait(timeout=10) for process in processes], [0, 0])
        snapshot = PronunciationDictionary(self.root / "parallel").snapshot()
        self.assertEqual(snapshot["revision"], 2)
        self.assertEqual({entry["normalized_word"] for entry in snapshot["entries"]}, {"дилон", "лера"})

    def test_migration_is_idempotent_and_conflicts_are_not_auto(self) -> None:
        class FakeLibrary:
            books_root = self.root / "books"

            def list_book_profiles(inner_self):
                return [Path("one.json"), Path("two.json")]

            def load_book_profile(inner_self, name, allow_disabled=False):
                number = 1 if name == "one.json" else 2
                return {"pronunciation_overrides": {
                    "schema_version": 1,
                    "revision": 1,
                    "entries": [{
                        "scope": "BOOK", "word": "замок", "vowel_number": number,
                        "display": "за́мок" if number == 1 else "замо́к", "actor": "OWNER",
                    }],
                }}

        library = FakeLibrary()
        first = migrate_book_rules(library, self.store)
        self.assertEqual(first["considered_book_rules"], 2)
        self.assertEqual(first["conflicts_created"], 1)
        self.assertEqual(self.store.snapshot()["entries"][0]["mode"], "REVIEW_REQUIRED")
        revision = self.store.snapshot()["revision"]
        second = migrate_book_rules(library, self.store)
        self.assertEqual(second["changed_entries"], 0)
        self.assertEqual(self.store.snapshot()["revision"], revision)

    def test_legacy_known_homograph_auto_is_repaired_once(self) -> None:
        first = self.store.ensure_created()
        self.assertTrue(first["created"])
        now = "2026-09-05T00:00:00+00:00"
        legacy = {
            "schema_version": 1,
            "revision": 1,
            "entries": [{
                "entry_id": "PRON-GLOBAL-LEGACYZAMOK1",
                "normalized_word": "замок",
                "word": "замок",
                "mode": "AUTO",
                "preferred": {"vowel_number": 2, "display": "замо́к"},
                "variants": [{"vowel_number": 2, "display": "замо́к"}],
                "actor": "OWNER",
                "source": "STUDIO_CORRECTION",
                "created_at": now,
                "updated_at": now,
            }],
        }
        self.store.path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        os.chmod(self.store.path, 0o600)
        repaired = self.store.repair_known_contextual_entries()
        self.assertTrue(repaired["changed"])
        entry = self.store.snapshot()["entries"][0]
        self.assertEqual(entry["mode"], "REVIEW_REQUIRED")
        self.assertIsNone(entry["preferred"])
        self.assertEqual(
            {variant["display"] for variant in entry["variants"]},
            {"за́мок", "замо́к"},
        )
        revision = self.store.snapshot()["revision"]
        repeated = self.store.repair_known_contextual_entries()
        self.assertFalse(repeated["changed"])
        self.assertEqual(self.store.snapshot()["revision"], revision)

    def test_contextual_review_only_resolves_exact_current_evidence(self) -> None:
        text = "старый замок и новый замок"
        first_start = text.index("замок")
        first_end = first_start + len("замок")
        sha = hashlib.sha256(text.encode()).hexdigest()
        occurrence = [{
            "scope": "OCCURRENCE",
            "word": "замок",
            "start": first_start,
            "end": first_end,
            "text_sha256": sha,
        }]
        items = contextual_review_items(
            text, occurrence, working_copy_sha256=sha
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["start"], text.rindex("замок"))
        stale = contextual_review_items(
            text, occurrence, working_copy_sha256="0" * 64
        )
        self.assertEqual(len(stale), 2)

    def test_contextual_review_context_uses_readable_word_boundaries(self) -> None:
        text = (
            "Это достаточно длинное начало предложения, чтобы окно контекста "
            "не начиналось посреди слова: старый замок стоял на холме, а дальше "
            "шла ещё одна достаточно длинная часть предложения для проверки."
        )
        item = contextual_review_items(text)[0]
        self.assertTrue(item["context"].startswith("… "))
        self.assertTrue(item["context"].endswith(" …"))
        self.assertIn("старый замок стоял на холме", item["context"])


if __name__ == "__main__":
    unittest.main()
