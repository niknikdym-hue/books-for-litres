from __future__ import annotations

import select
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from production_authority_lock import production_authority_lock


class ProductionAuthorityLockTests(unittest.TestCase):
    def test_shared_assembly_reader_blocks_exclusive_production_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = (
                "import pathlib,sys; "
                f"sys.path.insert(0,{str(ROOT)!r}); "
                "from production_authority_lock import production_authority_lock; "
                f"root=pathlib.Path({str(root)!r}); "
                "ctx=production_authority_lock(root,provider='openai',book_slug='demo-book',"
                "job_id='chapter-1',profile_id='openai_cedar',exclusive=True); "
                "ctx.__enter__(); print('acquired',flush=True); ctx.__exit__(None,None,None)"
            )
            with production_authority_lock(
                root,
                provider="openai",
                book_slug="demo-book",
                job_id="chapter-1",
                profile_id="openai_cedar",
                exclusive=False,
            ):
                process = subprocess.Popen(
                    [sys.executable, "-c", script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                self.assertEqual(ready, [])
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stdout.strip(), "acquired")


if __name__ == "__main__":
    unittest.main()
