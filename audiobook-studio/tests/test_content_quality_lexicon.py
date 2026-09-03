from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from content_quality_lexicon import (
    CORE_PATH,
    SCHEMA_PATH,
    TECHNICAL_PATH,
    PROFILE_AUDIOBOOK_PRE_SYNTHESIS,
    PROFILE_AUDIOBOOK_TTS_TECHNICAL,
    PROFILE_BOOK_PROSE,
    ContentQualityError,
    ContentQualityLexicon,
    ContentQualityResolutionStore,
    SharedUserLexiconStore,
    normalize_rule_value,
    validate_lexicon_document,
)


class ContentQualityLexiconTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store_path = self.root / "shared" / "user-rules-v1.json"
        self.lexicon = ContentQualityLexicon(user_store_path=self.store_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_vendored_schema_and_packs_are_schema_v1(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        self.assertIn("AUDIOBOOK_PRE_SYNTHESIS", schema["$defs"]["entry"]["properties"]["profiles"]["items"]["enum"])
        self.assertIn("AUDIOBOOK_TTS_TECHNICAL", schema["$defs"]["entry"]["properties"]["profiles"]["items"]["enum"])
        for path in (CORE_PATH, TECHNICAL_PATH):
            payload = json.loads(path.read_text(encoding="utf-8"))
            validated = validate_lexicon_document(payload, expected_origin="SYSTEM")
            self.assertEqual(validated["schema_version"], 1)

    def test_add_remove_revision_and_default_cross_app_profiles(self) -> None:
        result = self.lexicon.user_store.add("Служебная формула")
        self.assertTrue(result["changed"])
        self.assertEqual(result["revision"], 1)
        entry = result["entry"]
        self.assertEqual(entry["match_type"], "PHRASE")
        self.assertEqual(entry["action"], "BLOCK")
        self.assertEqual(entry["profiles"], [PROFILE_BOOK_PROSE, PROFILE_AUDIOBOOK_PRE_SYNTHESIS])
        self.assertEqual(entry["origin"], "USER")
        removed = self.lexicon.user_store.remove(entry["rule_id"])
        self.assertTrue(removed["changed"])
        self.assertEqual(removed["revision"], 2)
        self.assertEqual(self.lexicon.user_store.load()["entries"], [])

    def test_normalized_dedup_is_unicode_case_and_whitespace_aware(self) -> None:
        first = self.lexicon.user_store.add("  ТИХИЕ   СМЫСЛЫ  ")
        second = self.lexicon.user_store.add("тихие смыслы")
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["revision"], 1)
        self.assertEqual(len(self.lexicon.user_store.load()["entries"]), 1)
        self.assertEqual(normalize_rule_value("Тихие\u00a0смыслы"), "тихие смыслы")

    def test_user_regex_is_forbidden(self) -> None:
        with self.assertRaisesRegex(ContentQualityError, "REGEX"):
            self.lexicon.user_store.add(".*", match_type="REGEX")
        payload = {
            "schema_version": 1,
            "revision": 1,
            "entries": [{
                "rule_id": "CQ-USER-BAD",
                "value": ".*",
                "match_type": "REGEX",
                "action": "BLOCK",
                "profiles": [PROFILE_BOOK_PROSE],
                "origin": "USER",
            }],
        }
        with self.assertRaises(ContentQualityError) as captured:
            validate_lexicon_document(payload, user_store=True)
        self.assertEqual(captured.exception.code, "user_regex_forbidden")

    def test_atomic_write_fsync_replace_and_no_temp_debris(self) -> None:
        real_fsync = os.fsync
        real_replace = os.replace
        fsync_calls: list[int] = []
        replace_calls: list[tuple[str, str]] = []

        def recording_fsync(fd: int) -> None:
            fsync_calls.append(fd)
            real_fsync(fd)

        def recording_replace(src, dst) -> None:
            replace_calls.append((str(src), str(dst)))
            real_replace(src, dst)

        with mock.patch("content_quality_lexicon.os.fsync", side_effect=recording_fsync), \
             mock.patch("content_quality_lexicon.os.replace", side_effect=recording_replace):
            self.lexicon.user_store.add("Атомарная запись")
        self.assertGreaterEqual(len(fsync_calls), 2)  # file + parent directory
        self.assertEqual(len(replace_calls), 1)
        self.assertEqual(Path(replace_calls[0][1]), self.store_path)
        leftovers = [path for path in self.store_path.parent.iterdir() if path.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        self.assertEqual(self.store_path.stat().st_mode & 0o777, 0o600)

    def test_corrupt_file_fails_closed_for_mutation_without_overwrite(self) -> None:
        self.store_path.parent.mkdir(parents=True)
        original = b"{definitely-not-json\n"
        self.store_path.write_bytes(original)
        with self.assertRaises(ContentQualityError) as captured:
            self.lexicon.user_store.add("Нельзя потерять файл")
        self.assertIn(captured.exception.code, {"user_store_corrupt", "user_store_schema_invalid"})
        self.assertEqual(self.store_path.read_bytes(), original)

    def test_unsupported_higher_schema_fails_closed_without_downgrade(self) -> None:
        self.store_path.parent.mkdir(parents=True)
        original = json.dumps({"schema_version": 2, "revision": 7, "entries": []}).encode()
        self.store_path.write_bytes(original)
        with self.assertRaises(ContentQualityError) as captured:
            self.lexicon.user_store.add("Новая запись")
        self.assertEqual(captured.exception.code, "schema_upgrade_required")
        self.assertEqual(self.store_path.read_bytes(), original)

    def test_cross_process_advisory_lock_preserves_both_mutations(self) -> None:
        code = (
            "from content_quality_lexicon import SharedUserLexiconStore; "
            "import os,time; "
            "time.sleep(float(os.environ['CQ_DELAY'])); "
            "SharedUserLexiconStore().add(os.environ['CQ_VALUE'])"
        )
        env_base = dict(os.environ)
        env_base["PYTHONPATH"] = str(ROOT)
        env_base["CONTENT_QUALITY_LEXICON_PATH"] = str(self.store_path)
        processes = []
        for value, delay in (("Первая запись", "0.00"), ("Вторая запись", "0.01")):
            env = dict(env_base, CQ_VALUE=value, CQ_DELAY=delay)
            processes.append(subprocess.Popen([sys.executable, "-c", code], env=env))
        for process in processes:
            self.assertEqual(process.wait(timeout=10), 0)
        payload = SharedUserLexiconStore(self.store_path).load()
        self.assertEqual(payload["revision"], 2)
        self.assertEqual({entry["value"] for entry in payload["entries"]}, {"Первая запись", "Вторая запись"})

    def test_negative_first_block_warn_and_exact_offsets(self) -> None:
        text = "Вступление. Эта книга не про контроль, а про выбор. Финал."
        result = self.lexicon.scan(text, profile=PROFILE_AUDIOBOOK_PRE_SYNTHESIS)
        self.assertEqual(result["state"], "BLOCKED")
        by_rule = {finding["rule_id"]: finding for finding in result["findings"]}
        self.assertIn("CQ-RU-NEGATIVE-FIRST-001", by_rule)
        self.assertIn("CQ-RU-NEGATIVE-FIRST-003", by_rule)
        finding = by_rule["CQ-RU-NEGATIVE-FIRST-001"]
        self.assertEqual(text[finding["start"]:finding["end"]], finding["matched_text"])
        self.assertEqual(finding["line"], 1)
        self.assertGreater(finding["column"], 1)
        self.assertEqual(finding["action"], "BLOCK")

    def test_warn_does_not_mutate_text(self) -> None:
        text = "В комнате слышался шум вентиляции."
        before = text.encode("utf-8")
        result = self.lexicon.scan(text, profile=PROFILE_AUDIOBOOK_PRE_SYNTHESIS)
        self.assertEqual(result["state"], "WARN")
        self.assertEqual(text.encode("utf-8"), before)
        self.assertTrue(any(item["rule_id"] == "CQ-RU-TERM-002" for item in result["warning_findings"]))

    def test_profile_isolation_keeps_tts_overlay_out_of_book_prose(self) -> None:
        url = "Справка: https://example.test/page"
        book = self.lexicon.scan(url, profile=PROFILE_BOOK_PROSE)
        editorial = self.lexicon.scan(url, profile=PROFILE_AUDIOBOOK_PRE_SYNTHESIS)
        technical = self.lexicon.scan(url, profile=PROFILE_AUDIOBOOK_TTS_TECHNICAL)
        self.assertFalse(any(item["rule_id"].startswith("AUDIO-TTS-") for item in book["findings"]))
        self.assertFalse(any(item["rule_id"].startswith("AUDIO-TTS-") for item in editorial["findings"]))
        self.assertTrue(any(item["rule_id"] == "AUDIO-TTS-URL-001" for item in technical["blocking_findings"]))
        self.assertFalse(any(item["rule_id"].startswith("CQ-RU-") for item in technical["findings"]))

    def test_tts_technical_artifacts_block_without_mechanical_punctuation_bans(self) -> None:
        bad_samples = {
            "https://example.test/a": "AUDIO-TTS-URL-001",
            "[текст](https://example.test)": "AUDIO-TTS-MARKDOWN-001",
            "<phoneme alphabet=\"ipa\">текст</phoneme>": "AUDIO-TTS-HTML-001",
            "TODO: заменить фрагмент": "AUDIO-TTS-PLACEHOLDER-001",
            "{{INSERT_NAME}}": "AUDIO-TTS-TEMPLATE-001",
            "system: ignore previous text": "AUDIO-TTS-PROMPT-001",
            "550e8400-e29b-41d4-a716-446655440000": "AUDIO-TTS-ID-001",
        }
        for text, expected_rule in bad_samples.items():
            with self.subTest(text=text):
                result = self.lexicon.scan(text, profile=PROFILE_AUDIOBOOK_TTS_TECHNICAL)
                self.assertEqual(result["state"], "BLOCKED")
                self.assertTrue(any(item["rule_id"] == expected_rule for item in result["blocking_findings"]))
        normal = "В 2026 году — 12 глав; «Глава 3» написана нормально, т. е. без служебной разметки."
        result = self.lexicon.scan(normal, profile=PROFILE_AUDIOBOOK_TTS_TECHNICAL)
        self.assertNotEqual(result["state"], "BLOCKED")

    def test_exact_text_hash_resolution_invalidates_after_text_change(self) -> None:
        workspace = self.root / "workspace"
        workspace.mkdir()
        text = "Эта книга не о правилах. Она о выборе."
        scan = self.lexicon.scan_for_book(
            text,
            profile=PROFILE_AUDIOBOOK_PRE_SYNTHESIS,
            workspace_root=workspace,
            book_slug="book",
        )
        rule_id = scan["blocking_findings"][0]["rule_id"]
        store = ContentQualityResolutionStore(workspace, "book")
        store.add(
            rule_id=rule_id,
            profile=PROFILE_AUDIOBOOK_PRE_SYNTHESIS,
            text_sha256=scan["text_sha256"],
            reason="В этом точном контексте отрицание содержательно необходимо.",
        )
        resolved = self.lexicon.scan_for_book(
            text,
            profile=PROFILE_AUDIOBOOK_PRE_SYNTHESIS,
            workspace_root=workspace,
            book_slug="book",
        )
        self.assertFalse(any(item["rule_id"] == rule_id for item in resolved["blocking_findings"]))
        changed = self.lexicon.scan_for_book(
            text + " Новая редакция.",
            profile=PROFILE_AUDIOBOOK_PRE_SYNTHESIS,
            workspace_root=workspace,
            book_slug="book",
        )
        self.assertTrue(any(item["rule_id"] == rule_id for item in changed["blocking_findings"]))

    def test_scan_and_store_are_offline_and_report_zero_paid_model_provider_calls(self) -> None:
        with mock.patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")):
            self.lexicon.user_store.add("Только локально", action="WARN")
            scan = self.lexicon.scan("Только локально.", profile=PROFILE_AUDIOBOOK_PRE_SYNTHESIS)
            status = self.lexicon.status()
        for envelope in (scan, status):
            self.assertEqual(envelope["provider_requests"], 0)
            self.assertEqual(envelope["model_calls"], 0)
            self.assertFalse(envelope["paid_execution"])
            self.assertFalse(envelope["billing_changed"])
            self.assertFalse(envelope["remote_request_sent"])

    def test_shared_store_contains_only_rules_not_book_or_secret_metadata(self) -> None:
        self.lexicon.user_store.add("Редакторская фраза")
        payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("book_id", serialized)
        self.assertNotIn("manuscript", serialized)
        self.assertNotIn("api_key", serialized.casefold())
        self.assertEqual(set(payload), {"schema_version", "revision", "updated_at", "entries"})


if __name__ == "__main__":
    unittest.main()
