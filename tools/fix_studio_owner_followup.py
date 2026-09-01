from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        if new in text:
            return
        raise SystemExit(f"missing anchor {label}: {path}")
    if count != 1:
        raise SystemExit(f"ambiguous anchor {label}: {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    assembly = ROOT / "audiobook-studio/chapter_assembly.py"
    replace_once(
        assembly,
        '''        contract = {\n            "chapter_cue": chapter_cue,\n            "schema_version": ASSEMBLY_SCHEMA_VERSION,\n''',
        '''        contract = {\n            "schema_version": ASSEMBLY_SCHEMA_VERSION,\n''',
        "remove-null-cue-from-legacy-identity",
    )
    replace_once(
        assembly,
        '''            },\n        }\n        return _canonical_hash(contract)\n\n    @staticmethod\n    def _input_rates''',
        '''            },\n        }\n        # Preserve the exact legacy assembly identity when the author leaves the\n        # optional chapter cue disabled. Enabling/changing a cue intentionally\n        # creates a new downstream assembly identity without re-synthesizing TTS.\n        if chapter_cue is not None:\n            contract["chapter_cue"] = chapter_cue\n        return _canonical_hash(contract)\n\n    @staticmethod\n    def _input_rates''',
        "conditional-cue-identity",
    )

    native_test = ROOT / "audiobook-studio/tests/test_native_ui_bridge.py"
    replace_once(
        native_test,
        '        self.assertIn("Source integrity", source)\n',
        '        self.assertIn("Исходник защищён", source)\n',
        "human-source-integrity-label",
    )

    old_credit = "Елена Дилон. Хватит себя обесценивать. Читает Dilon Voices."
    new_credit = "Елена Ди́лон. Хватит себя обесценивать. Читает Dilon Voices."
    tests_root = ROOT / "audiobook-studio/tests"
    for path in tests_root.glob("test_dilon*.py"):
        text = path.read_text(encoding="utf-8")
        if old_credit in text:
            path.write_text(text.replace(old_credit, new_credit), encoding="utf-8")

    state_doc = ROOT / "audiobook-studio/docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md"
    text = state_doc.read_text(encoding="utf-8")
    if old_credit in text:
        state_doc.write_text(text.replace(old_credit, new_credit), encoding="utf-8")

    owner_test = ROOT / "audiobook-studio/tests/test_owner_production_flow_source.py"
    text = owner_test.read_text(encoding="utf-8")
    marker = '        self.assertIn("chapter_cue_changed_during_assembly", assembly)\n'
    addition = marker + '        self.assertIn(\'if chapter_cue is not None:\\n            contract["chapter_cue"] = chapter_cue\', assembly)\n'
    if addition not in text:
        if marker not in text:
            raise SystemExit("missing owner test cue marker")
        owner_test.write_text(text.replace(marker, addition, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
