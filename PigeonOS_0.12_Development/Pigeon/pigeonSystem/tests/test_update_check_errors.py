"""Update check must report the real failure instead of a generic "could not reach"."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import update_check as uc  # noqa: E402

_CURL_404 = "curl: (22) The requested URL returned error: 404"
_CURL_DNS = "curl: (6) Could not resolve host: raw.githubusercontent.com"


class ClassifyFetchErrorTests(unittest.TestCase):
    def test_curl_http_status_becomes_http_code(self) -> None:
        self.assertEqual(uc._classify_fetch_error(_CURL_404), "HTTP 404")
        self.assertEqual(
            uc._classify_fetch_error("curl: (22) The requested URL returned error: 403 Forbidden"),
            "HTTP 403",
        )

    def test_network_errors_pass_through(self) -> None:
        self.assertEqual(uc._classify_fetch_error(_CURL_DNS), _CURL_DNS)

    def test_fetch_version_text_maps_curl_404(self) -> None:
        with mock.patch.object(uc, "github_token", return_value=""), mock.patch.object(
            uc, "_linux_curl_get_simple", return_value=None
        ), mock.patch.object(uc, "github_http_get", side_effect=OSError(_CURL_404)):
            body, err = uc._fetch_version_text("https://example/version.py", timeout_s=1)
        self.assertIsNone(body)
        self.assertEqual(err, "HTTP 404")


class FetchRemoteVersionMessageTests(unittest.TestCase):
    def _run(self, err: str) -> str | None:
        with mock.patch.object(uc, "github_token", return_value=""), mock.patch.object(
            uc, "_fetch_version_text", return_value=(None, err)
        ):
            remote, msg, _url, _branch = uc.fetch_remote_version_tuple(timeout_s=1)
        self.assertIsNone(remote)
        return msg

    def test_network_failure_includes_curl_detail(self) -> None:
        msg = self._run(_CURL_DNS) or ""
        self.assertIn("Could not reach GitHub", msg)
        self.assertIn("Could not resolve host", msg)

    def test_404_on_public_repo_is_not_reported_as_private(self) -> None:
        msg = self._run("HTTP 404") or ""
        self.assertIn("version.py was not found", msg)
        self.assertNotIn("private", msg)


if __name__ == "__main__":
    unittest.main()
