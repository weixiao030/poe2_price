import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "物价补丁"
    / "tools"
    / "price_sources"
    / "health.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("source_health", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SourceHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.health = load_module()

    def payload(self):
        return {
            "core": {"league": "runes", "epoch": 1783656000},
            "lines": [
                {"name": "Divine Orb", "value": 571.3, "count": 20},
                {"name": "Exalted Orb", "value": 1, "count": 500},
                {"name": "Chaos Orb", "value": 0.3, "count": 100},
            ],
        }

    def common(self):
        return {
            "expected_root": "object",
            "http": {
                "url": "https://example.invalid/api",
                "status_code": 200,
                "content_type": "application/json; charset=utf-8",
                "elapsed_ms": 25,
                "content_bytes": 1024,
            },
            "item_count": 3,
            "match_count": 3,
            "item_names": ["Divine Orb", "Exalted Orb", "Chaos Orb"],
            "discovered_categories": ["Currency", "Fragments"],
            "enabled_categories": ["Currency", "Fragments"],
            "succeeded_categories": ["Currency", "Fragments"],
            "failed_categories": [],
            "freshness_timestamp": "2026-07-10T08:00:00Z",
            "max_age_seconds": 7200,
            "now": datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc),
            "key_fields": ["name", "value"],
        }

    def test_healthy_report_is_json_serializable_and_complete(self):
        report = self.health.evaluate_source_health(
            "poe.ninja", self.payload(), **self.common()
        )

        self.assertEqual(report.state, "healthy")
        self.assertTrue(report.usable)
        self.assertFalse(report.is_failure)
        value = report.to_dict()
        self.assertEqual(value["counts"]["items"], 3)
        self.assertEqual(value["counts"]["matches"], 3)
        self.assertEqual(value["counts"]["categories"]["discovered"], 2)
        self.assertEqual(value["references"]["missing"], [])
        self.assertEqual(value["freshness"]["age_seconds"], 3600.0)
        self.assertEqual(value["http"]["content_type"], "application/json; charset=utf-8")
        self.assertEqual(len(value["schema"]["digest"]), 64)
        json.dumps(value, ensure_ascii=False)

    def test_optional_category_failure_is_partial_not_failed(self):
        options = self.common()
        options["succeeded_categories"] = ["Currency"]
        options["failed_categories"] = ["Fragments"]

        report = self.health.evaluate_source_health(
            "poe.ninja", self.payload(), **options
        )

        self.assertEqual(report.state, "partial")
        self.assertTrue(report.usable)
        self.assertFalse(report.is_failure)
        self.assertFalse(report.is_failed)
        self.assertIn("category_failures", [issue.code for issue in report.issues])

    def test_expected_html_content_type_is_healthy_for_html_adapter(self):
        options = self.common()
        options["http"] = {
            "status_code": 200,
            "content_type": "text/html; charset=utf-8",
        }
        report = self.health.evaluate_source_health(
            "poe2db",
            self.payload(),
            accepted_content_types=("text/html",),
            **options,
        )

        self.assertEqual(report.state, "healthy")

    def test_stale_timestamp_has_dedicated_state(self):
        options = self.common()
        options["max_age_seconds"] = 1800

        report = self.health.evaluate_source_health(
            "poe2scout", self.payload(), **options
        )

        self.assertEqual(report.state, "stale")
        self.assertTrue(report.usable)
        self.assertEqual(report.freshness.age_seconds, 3600.0)
        self.assertTrue(report.freshness.stale)

    def test_zero_items_and_zero_matches_are_empty(self):
        for item_count, match_count, code in (
            (0, 0, "empty_items"),
            (3, 0, "empty_matches"),
        ):
            with self.subTest(item_count=item_count, match_count=match_count):
                options = self.common()
                options.update(
                    item_count=item_count,
                    match_count=match_count,
                    item_names=None,
                )
                report = self.health.evaluate_source_health(
                    "source", self.payload(), **options
                )
                self.assertEqual(report.state, "empty")
                self.assertTrue(report.is_failure)
                self.assertIn(code, [issue.code for issue in report.issues])

    def test_wrong_root_or_missing_reference_is_incompatible(self):
        wrong_root = self.common()
        wrong_root["item_names"] = None
        report = self.health.evaluate_source_health(
            "poecurrency", [self.payload()], **wrong_root
        )
        self.assertEqual(report.state, "incompatible")
        self.assertEqual(report.issues[0].code, "unexpected_root")

        missing_reference = self.common()
        missing_reference["item_names"] = ["Divine Orb", "Chaos Orb"]
        report = self.health.evaluate_source_health(
            "poecurrency", self.payload(), **missing_reference
        )
        self.assertEqual(report.state, "incompatible")
        self.assertEqual(report.references.missing, ("Exalted Orb",))
        self.assertIn("missing_references", [issue.code for issue in report.issues])

    def test_schema_fingerprint_ignores_values_and_array_length(self):
        first = self.health.schema_fingerprint(
            self.payload(), key_fields=("name", "value"), categories=("Currency",)
        )
        second_payload = {
            "core": {"league": "other", "epoch": 1},
            "lines": [
                {"name": "Mirror of Kalandra", "value": 999999.0, "count": 1},
                {"name": "Chaos Orb", "value": 2, "count": 2},
            ],
        }
        second = self.health.schema_fingerprint(
            second_payload, key_fields=("value", "name"), categories=("Currency",)
        )

        self.assertEqual(first.digest, second.digest)
        serialized = json.dumps(first.to_dict(), ensure_ascii=False)
        self.assertNotIn("571.3", serialized)
        self.assertNotIn("Divine Orb", serialized)
        self.assertNotIn("runes", serialized)

    def test_schema_drift_reports_fields_types_and_categories(self):
        baseline_payload = {
            "core": {"league": "runes"},
            "lines": [{"name": "Divine Orb", "value": 571.3, "old": True}],
        }
        current_payload = {
            "core": {"league": "runes", "realm": "poe2"},
            "lines": [{"name": "Divine Orb", "value": "571.3", "volume": 20}],
        }
        baseline = self.health.schema_fingerprint(
            baseline_payload,
            key_fields=("name", "value"),
            categories=("Currency", "Fragments"),
        )
        current = self.health.schema_fingerprint(
            current_payload,
            key_fields=("name", "value", "volume"),
            categories=("Currency", "Runes"),
        )

        drift = self.health.compare_schema(baseline.to_dict(), current)

        self.assertTrue(drift.has_drift)
        self.assertEqual(
            drift.added_fields, ("#/core/realm", "#/lines/*/volume")
        )
        self.assertEqual(drift.removed_fields, ("#/lines/*/old",))
        self.assertEqual(
            drift.changed_field_types,
            (("#/lines/*/value", ("number",), ("string",)),),
        )
        self.assertEqual(drift.added_categories, ("Runes",))
        self.assertEqual(drift.removed_categories, ("Fragments",))
        self.assertEqual(drift.added_key_fields, ("volume",))

        options = self.common()
        options.update(
            key_fields=("name", "value", "volume"),
            discovered_categories=("Currency", "Runes"),
            enabled_categories=("Currency", "Runes"),
            succeeded_categories=("Currency", "Runes"),
            baseline_schema=baseline,
        )
        report = self.health.evaluate_source_health(
            "poe.ninja", current_payload, **options
        )
        self.assertEqual(report.state, "partial")
        self.assertFalse(report.is_failure)
        self.assertEqual(report.drift.added_categories, ("Runes",))

    def test_transport_failure_and_skipped_are_distinct(self):
        failed = self.health.failed_source_health(
            "poe2db", TimeoutError("deadline"), http={"status_code": 503}
        )
        skipped = self.health.skipped_source_health("poe2db", "disabled")

        self.assertEqual(failed.state, "failed")
        self.assertTrue(failed.is_failed)
        self.assertEqual(skipped.state, "skipped")
        self.assertFalse(skipped.is_failure)
        json.dumps([failed.to_dict(), skipped.to_dict()])


if __name__ == "__main__":
    unittest.main()
