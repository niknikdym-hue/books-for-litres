from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from content_quality_lexicon import PROFILE_BOOK_PROSE, ContentQualityLexicon


class ContentQualityPhraseBoundaryTests(unittest.TestCase):
    def test_eto_pro_rule_does_not_block_normal_problem_words(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lexicon = ContentQualityLexicon(
                user_store_path=Path(temporary) / "user-rules-v1.json"
            )
            normal = lexicon.scan(
                "Если релевантного доказательства нет, это проблема рыночной позиции.",
                profile=PROFILE_BOOK_PROSE,
            )
            self.assertFalse(
                any(
                    finding["rule_id"] == "CQ-RU-PHRASE-001"
                    for finding in normal["findings"]
                )
            )

    def test_eto_pro_rule_still_blocks_meta_formula(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lexicon = ContentQualityLexicon(
                user_store_path=Path(temporary) / "user-rules-v1.json"
            )
            bad = lexicon.scan(
                "Это про доверие и внутреннюю опору.",
                profile=PROFILE_BOOK_PROSE,
            )
            self.assertTrue(
                any(
                    finding["rule_id"] == "CQ-RU-PHRASE-001"
                    and finding["action"] == "BLOCK"
                    for finding in bad["blocking_findings"]
                )
            )


if __name__ == "__main__":
    unittest.main()
