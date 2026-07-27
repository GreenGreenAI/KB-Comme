import json
import unittest
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path

from tradeflow.integration.source_monitor import (
    SourceMonitorSpec,
    check_all,
    fetch_and_check,
    parse_monitor_specs,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self.body[:size]

    def getcode(self) -> int:
        return 200

    def geturl(self) -> str:
        return "https://official.example/rule"


class CheckAllTests(unittest.TestCase):
    """One dead host must not decide the freshness of the other fourteen.

    `www.koreaexim.go.kr` serves an incomplete certificate chain today, and
    before isolation that single failure aborted the whole run — leaving no
    verification at all, which makes every rule fail closed.
    """

    def _specs(self) -> tuple[SourceMonitorSpec, ...]:
        return tuple(
            SourceMonitorSpec(
                name,
                f"https://official.example/{name}",
                ("rule text",),
                "metadata_and_fingerprint_only",
            )
            for name in ("A", "DEAD", "C")
        )

    def test_a_failing_source_becomes_a_recorded_result(self) -> None:
        def opener(request, **_kwargs):
            if "DEAD" in request.full_url:
                raise OSError("certificate verify failed")
            return _Response(b"<html><body>rule text</body></html>")

        results = check_all(
            self._specs(),
            opener=opener,
            now=lambda: datetime(2026, 7, 27, tzinfo=UTC),
        )

        by_id = {item.source_id: item for item in results}
        self.assertEqual(3, len(results))
        self.assertEqual("verified", by_id["A"].status)
        self.assertEqual("verified", by_id["C"].status)
        self.assertEqual("unreachable", by_id["DEAD"].status)
        self.assertIn("certificate verify failed", by_id["DEAD"].error)

    def test_an_unreachable_source_never_claims_a_fingerprint(self) -> None:
        """An empty hash must not look like a body we actually read."""

        def opener(request, **_kwargs):
            raise OSError("boom")

        (result,) = check_all(
            self._specs()[1:2],
            opener=opener,
            now=lambda: datetime(2026, 7, 27, tzinfo=UTC),
        )

        self.assertEqual("", result.response_sha256)
        self.assertEqual(0, result.http_status)
        self.assertEqual((), result.missing_markers)


class SourceMonitorTests(unittest.TestCase):
    def test_scripts_and_styles_do_not_satisfy_visible_marker(self) -> None:
        spec = SourceMonitorSpec(
            "S1",
            "https://official.example/rule",
            ("visible rule", "script-only"),
            "metadata_and_fingerprint_only",
        )
        body = (
            b"<html><script>script-only</script>"
            b"<body>visible   rule</body></html>"
        )

        result = fetch_and_check(
            spec,
            opener=lambda *_args, **_kwargs: _Response(body),
            now=lambda: datetime(2026, 7, 27, tzinfo=UTC),
        )

        self.assertEqual("changed_or_unavailable", result.status)
        self.assertEqual(("script-only",), result.missing_markers)
        self.assertTrue(result.response_sha256.startswith("sha256:"))

    def test_all_visible_markers_verify_without_retaining_body(self) -> None:
        spec = SourceMonitorSpec(
            "S1",
            "https://official.example/rule",
            ("외국환 거래", "USD 5,000"),
            "metadata_and_fingerprint_only",
        )
        body = "<p>외국환 거래</p><p>USD 5,000</p>".encode()

        result = fetch_and_check(
            spec,
            opener=lambda *_args, **_kwargs: _Response(body),
            now=lambda: datetime(2026, 7, 27, tzinfo=UTC),
        )

        self.assertEqual("verified", result.status)
        self.assertNotIn("body", result.as_dict())

    def test_manifest_monitors_registered_extract_sources(self) -> None:
        manifest = json.loads(
            (PROJECT_ROOT / "knowledge" / "source_monitors.json").read_text(
                encoding="utf-8"
            )
        )
        registry = json.loads(
            (PROJECT_ROOT / "knowledge" / "source_registry.json").read_text(
                encoding="utf-8"
            )
        )
        monitored = {
            item.source_id: item for item in parse_monitor_specs(manifest)
        }
        extracted = {
            item["source_id"]: item
            for item in registry["sources"]
            if item.get("extract_path")
        }

        self.assertEqual(set(extracted), set(monitored))
        for source_id, source in extracted.items():
            with self.subTest(source_id=source_id):
                self.assertEqual(source["url"], monitored[source_id].url)
                self.assertEqual(
                    "metadata_and_fingerprint_only",
                    monitored[source_id].storage_policy,
                )
        self.assertFalse(manifest["policy"]["raw_content_retention"])


if __name__ == "__main__":
    unittest.main()
