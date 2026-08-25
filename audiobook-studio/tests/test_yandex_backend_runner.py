from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backends.yandex_speechkit import shared_cache_execution_lock
from yandex_backend_runner import DEMO_TEXT, run_demo


class FakeBackend:
    def __init__(self, output_root: Path) -> None:
        self.config = SimpleNamespace(output_root=output_root)
        self.calls: list[dict[str, object]] = []
        self.called = threading.Event()

    def run_text_job(self, text: str, job_dir: Path, **kwargs: object) -> Path:
        self.calls.append({"text": text, "job_dir": job_dir, **kwargs})
        self.called.set()
        return job_dir / "joined.wav"


class YandexBackendRunnerTests(unittest.TestCase):
    def test_demo_waits_for_shared_cache_writer_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = FakeBackend(root / "renders/yandex")
            job_dir = root / "demo-job"

            with ThreadPoolExecutor(max_workers=1) as executor:
                with shared_cache_execution_lock(backend.config.output_root):
                    future = executor.submit(run_demo, backend, pricing=object(), job_dir=job_dir)
                    time.sleep(0.1)
                    self.assertFalse(future.done())
                    self.assertFalse(backend.called.is_set())
                self.assertEqual(future.result(timeout=3), job_dir / "joined.wav")
            self.assertTrue(backend.called.is_set())
            self.assertEqual(len(backend.calls), 1)
            self.assertEqual(backend.calls[0]["text"], DEMO_TEXT)
            self.assertEqual(backend.calls[0]["job_id"], "speechkit-demo")
            self.assertEqual(backend.calls[0]["scope"], "demo")


if __name__ == "__main__":
    unittest.main()
