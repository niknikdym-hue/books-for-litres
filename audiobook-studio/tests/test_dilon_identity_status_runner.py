from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import dilon_identity_status_runner as runner


class DilonIdentityStatusRunnerTests(unittest.TestCase):
    def test_status_for_selection_resolves_registry_slug_and_stays_offline(self) -> None:
        paths = SimpleNamespace(
            root=Path("/tmp/audiobook-studio-status-test"),
            books_root=Path("/tmp/audiobook-studio-status-test/books"),
            masters_root=Path("/tmp/audiobook-studio-status-test/masters"),
        )
        library = mock.Mock()
        library.resolve_book_profile.return_value = Path("книга-тест.json")
        expected = {
            "state": "BLOCKED",
            "book_slug": "книга-тест",
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
        }
        with mock.patch.object(runner, "load_workspace_paths", return_value=paths), mock.patch.object(
            runner, "BookLibrary", return_value=library
        ), mock.patch.object(
            runner, "current_dilon_identity_status", return_value=expected
        ) as status:
            result = runner.status_for_selection(book_name="книга-тест", job_id="chapter-ch001")
        self.assertEqual(result, expected)
        library.resolve_book_profile.assert_called_once_with("книга-тест")
        status.assert_called_once_with(
            workspace_root=paths.root,
            masters_root=paths.masters_root,
            identities_root=paths.root / "identities",
            book_slug="книга-тест",
            job_id="chapter-ch001",
        )

    def test_main_prints_machine_readable_json_only(self) -> None:
        payload = {
            "schema_version": 1,
            "state": "BLOCKED",
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
        }
        stdout = io.StringIO()
        with mock.patch.object(runner, "status_for_selection", return_value=payload), mock.patch(
            "sys.stdout", stdout
        ):
            exit_code = runner.main(["--status", "--book", "demo-book", "--job", "chapter-ch001"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), payload)


if __name__ == "__main__":
    unittest.main()
