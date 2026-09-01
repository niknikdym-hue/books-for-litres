from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ContentQualityProviderWiringTests(unittest.TestCase):
    def test_actual_app_injects_guard_into_both_paid_cloud_services(self) -> None:
        source = (ROOT / "audiobook_studio_app_runner.py").read_text(encoding="utf-8")
        self.assertIn("from content_quality_execution import hold_current_content_quality", source)
        self.assertGreaterEqual(source.count("content_quality_guard=_content_quality_execution"), 2)
        self.assertIn("with _content_quality_execution(book_name):", source)
        self.assertIn("QWEN_RUNNER", source)
        self.assertIn("OPENAI_RUNNER", source)

    def test_yandex_service_binds_gate_into_plan_and_rechecks_while_execution_is_fenced(self) -> None:
        source = (ROOT / "chapter_production.py").read_text(encoding="utf-8")
        self.assertIn("content_quality_guard: Callable[[str], Any] | None = None", source)
        self.assertIn("content_quality, quality_blockers = self._content_quality_status(profile_path.name)", source)
        self.assertIn('critical["content_quality_gate"]', source)
        self.assertIn('"content_quality": analysis["content_quality"]', source)
        barrier = source.index('with self.content_quality_guard(str(plan["book_file"])):')
        provider = source.index('output_path = run_provider_job()', barrier)
        self.assertLess(barrier, provider)

    def test_openai_service_binds_gate_into_plan_and_rechecks_inside_provider_lock(self) -> None:
        source = (ROOT / "paid_run.py").read_text(encoding="utf-8")
        self.assertIn("content_quality_guard: Callable[[str], Any] | None = None", source)
        self.assertIn("content_quality, quality_blockers = self._content_quality_status(source_path.name)", source)
        self.assertIn('critical["content_quality_gate"]', source)
        self.assertIn('"content_quality": analysis["content_quality"]', source)
        barrier = source.index('with self.content_quality_guard(str(plan["book_file"])):')
        provider = source.index("manifest_path, result = run_provider_segment()", barrier)
        self.assertLess(barrier, provider)

    def test_direct_openai_runner_preserves_paid_gate_and_canonical_lock_order(self) -> None:
        source = (ROOT / "openai_backend_runner.py").read_text(encoding="utf-8")
        self.assertIn("from content_quality_execution import hold_current_content_quality", source)
        paid_gate = source.index("if not backend.config.paid_execution_enabled:")
        production_lock = source.index("with production_authority_lock(", paid_gate)
        quality_lock = source.index("with hold_current_content_quality(", production_lock)
        provider = source.index("manifest = backend.run_text_job(", quality_lock)
        self.assertLess(paid_gate, production_lock)
        self.assertLess(production_lock, quality_lock)
        self.assertLess(quality_lock, provider)

    def test_universal_openai_delegation_is_not_a_content_quality_bypass(self) -> None:
        source = (ROOT / "content_quality_execution.py").read_text(encoding="utf-8")
        self.assertIn("_delegated_openai_child_owns_gate", source)
        self.assertIn('Path(sys.argv[0]).name == "audiobook_studio_app_runner.py"', source)
        self.assertIn('and "--run-openai" in sys.argv[1:]', source)
        self.assertIn('"state": "DEFERRED_TO_OPENAI_PROVIDER_RUNNER"', source)
        child = (ROOT / "openai_backend_runner.py").read_text(encoding="utf-8")
        self.assertIn("with hold_current_content_quality(", child)

    def test_shared_production_authority_lock_has_no_content_quality_policy_regression(self) -> None:
        source = (ROOT / "production_authority_lock.py").read_text(encoding="utf-8")
        self.assertNotIn("content_quality", source)
        self.assertNotIn("ContentQuality", source)
        self.assertIn("production_authority_lock", source)

    def test_execution_barrier_holds_shared_and_resolution_locks_during_validation(self) -> None:
        source = (ROOT / "content_quality_execution.py").read_text(encoding="utf-8")
        user_lock = source.index("engine.user_store.lock_path")
        resolution_lock = source.index("resolution_store.lock_path")
        validation = source.index("validate_prepared_content_quality(")
        yielding = source.index("yield evidence")
        self.assertLess(user_lock, resolution_lock)
        self.assertLess(resolution_lock, validation)
        self.assertLess(validation, yielding)


if __name__ == "__main__":
    unittest.main()
