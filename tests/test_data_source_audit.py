import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "物价补丁"
    / "tools"
    / "audit_price_sources.py"
)
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
BASELINE_PATH = MODULE_PATH.with_name("data_source_contract_baseline.json")
WORKFLOW_PATH = MODULE_PATH.parents[2] / ".github" / "workflows" / "audit-data-sources.yml"


def load_module():
    spec = importlib.util.spec_from_file_location("data_source_audit", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload, url="https://example.invalid/source"):
        self._payload = payload
        self.url = url
        self.status_code = 200
        self.text = payload if isinstance(payload, str) else json.dumps(payload)
        self.content = self.text.encode("utf-8")

    def json(self):
        return self._payload


class FakeDelegate:
    def __init__(self, responses):
        self.responses = responses
        self.total_timeout = 1

    def get(self, url, **_kwargs):
        value = self.responses[url]
        if isinstance(value, BaseException):
            raise value
        return FakeResponse(value, url=url)


class DataSourceAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = load_module()

    def league(self, source="auto"):
        return self.audit.LeagueSelection(
            scout="runes",
            poe_ninja="Runes of Aldur",
            source=source,
            discovery_url="https://example.invalid/leagues",
        )

    def source_entry(self, name, *, failed=(), state_error=None):
        if state_error is not None:
            health = self.audit.failed_source_health(name, state_error)
        else:
            health = self.audit.evaluate_source_health(
                name,
                {"lines": [{"name": "Divine Orb"}, {"name": "Exalted Orb"}]},
                expected_root="object",
                item_count=2,
                match_count=2,
                item_names=("Divine Orb", "Exalted Orb"),
                discovered_categories=("core", "optional"),
                enabled_categories=("core", "optional"),
                succeeded_categories=("core",) if failed else ("core", "optional"),
                failed_categories=failed,
            )
        return self.audit._entry(health, {"offline_fixture": True})

    def test_optional_category_partial_has_zero_exit_code(self):
        sources = {
            "first": self.source_entry("first", failed=("optional",)),
            "second": self.source_entry("second"),
        }

        overall = self.audit._overall(sources, self.league())

        self.assertEqual(overall["status"], "partial")
        self.assertEqual(overall["exit_code"], 0)
        self.assertEqual(overall["failed_sources"], [])
        self.assertEqual(overall["partial_sources"], ["first"])

    def test_run_audit_catches_one_source_and_continues(self):
        called = []

        def resolver(_client, _api_base):
            return self.league()

        def healthy(_client, _league, _baseline, _workers):
            called.append("healthy")
            return self.source_entry("healthy")

        def broken(_client, _league, _baseline, _workers):
            called.append("broken")
            raise TimeoutError("offline timeout fixture")

        def after(_client, _league, _baseline, _workers):
            called.append("after")
            return self.source_entry("after")

        report = self.audit.run_audit(
            object(),
            league_resolver=resolver,
            auditors=(("healthy", healthy), ("broken", broken), ("after", after)),
        )

        self.assertEqual(called, ["healthy", "broken", "after"])
        self.assertEqual(report["sources"]["broken"]["status"], "failed")
        self.assertEqual(report["sources"]["after"]["status"], "healthy")
        self.assertEqual(report["overall"]["exit_code"], 1)

    def test_tolerant_ninja_client_only_swallows_optional_failures(self):
        optional_url = (
            "https://poe.ninja/poe2/api/economy/exchange/current/overview"
            "?league=Runes+of+Aldur&type=Fragments"
        )
        currency_url = optional_url.replace("Fragments", "Currency")
        client = self.audit.RecordingClient(
            FakeDelegate(
                {
                    optional_url: TimeoutError("optional down"),
                    currency_url: TimeoutError("core down"),
                }
            )
        )
        tolerant = self.audit.TolerantNinjaClient(client)

        self.assertEqual(
            tolerant.get_json(optional_url),
            {"core": {}, "lines": [], "items": []},
        )
        self.assertIn("exchange:Fragments", tolerant.failures)
        with self.assertRaises(TimeoutError):
            tolerant.get_json(currency_url)

    def test_dynamic_astro_import_discovers_site_categories(self):
        page_url = "https://poe.ninja/poe2/economy/testleague/currency"
        component_url = "https://assets.poe.ninja/_astro/a.PageAnyHash.mjs"
        views_url = "https://assets.poe.ninja/_astro/a.ViewsAnyHash.mjs"
        responses = {
            page_url: (FIXTURE_DIR / "poe_ninja_currency_page.html").read_text(
                encoding="utf-8"
            ),
            component_url: (
                FIXTURE_DIR / "poe_ninja_overview_component.mjs"
            ).read_text(encoding="utf-8"),
            views_url: (FIXTURE_DIR / "poe_ninja_views_module.mjs").read_text(
                encoding="utf-8"
            ),
        }
        client = self.audit.RecordingClient(FakeDelegate(responses))

        result = self.audit.discover_poe_ninja_site_categories(
            client, "Test League", max_workers=2
        )

        self.assertEqual(result["page_url"], page_url)
        self.assertEqual(result["component_url"], component_url)
        self.assertEqual(result["contract_module_url"], views_url)
        self.assertEqual(
            [item["type"] for item in result["categories"]],
            ["Currency", "Fragments", "UniqueWeapons"],
        )
        self.assertEqual(result["categories"][-1]["available_views"], ["stash"])

    def test_site_discovery_falls_back_to_default_page_url(self):
        requested_url = "https://poe.ninja/poe2/economy/futureleague/currency"
        default_url = self.audit.builder.DEFAULT_POE_NINJA_CURRENCY_URL
        component_url = "https://assets.poe.ninja/_astro/a.PageAnyHash.mjs"
        views_url = "https://assets.poe.ninja/_astro/a.ViewsAnyHash.mjs"
        client = self.audit.RecordingClient(
            FakeDelegate(
                {
                    requested_url: TimeoutError("future slug fixture"),
                    default_url: (
                        FIXTURE_DIR / "poe_ninja_currency_page.html"
                    ).read_text(encoding="utf-8"),
                    component_url: (
                        FIXTURE_DIR / "poe_ninja_overview_component.mjs"
                    ).read_text(encoding="utf-8"),
                    views_url: (
                        FIXTURE_DIR / "poe_ninja_views_module.mjs"
                    ).read_text(encoding="utf-8"),
                }
            )
        )

        result = self.audit.discover_poe_ninja_site_categories(
            client, "Future League", max_workers=2
        )

        self.assertEqual(result["requested_page_url"], requested_url)
        self.assertEqual(result["page_url"], default_url)
        self.assertTrue(result["used_default_page_fallback"])

    def test_site_category_difference_forces_partial_but_not_failure(self):
        discovered = {
            "status": "ok",
            "categories": [
                {"type": "Currency", "available_views": ["exchange"]},
                {"type": "UniqueWeapons", "available_views": ["stash"]},
            ],
        }
        comparison = self.audit.compare_poe_ninja_site_categories(
            discovered,
            {"Currency": "exchange", "Fragments": "exchange"},
        )
        health = self.source_entry("poe.ninja")["health"]
        source_health = self.audit.evaluate_source_health(
            "poe.ninja",
            {"lines": [1]},
            expected_root="object",
            item_count=1,
            match_count=1,
            item_names=None,
            required_references=(),
        )
        entry = self.audit._entry(
            source_health,
            {"site_contract": comparison},
            partial_reasons=("site_category_drift",),
        )

        self.assertEqual(comparison["site_only"], ["UniqueWeapons"])
        self.assertEqual(comparison["configured_only"], ["Fragments"])
        self.assertTrue(comparison["has_drift"])
        self.assertEqual(entry["status"], "partial")
        self.assertFalse(health["is_failure"])
        self.assertEqual(
            self.audit._overall({"poe.ninja": entry}, self.league())["exit_code"],
            0,
        )

    def test_compact_contract_reports_category_and_field_drift(self):
        baseline = {
            "categories": ["Currency", "Fragments"],
            "field_sets": {"lines": ["id", "old"], "root": ["core"]},
        }

        drift = self.audit.compare_contract(
            baseline,
            ["Fragments", "Runes"],
            {"lines": ["id", "new"], "root": ["core", "items"]},
            baseline_expected=True,
        )
        entry = self.audit._entry(
            self.audit.evaluate_source_health(
                "source",
                {"lines": [1]},
                expected_root="object",
                item_count=1,
                match_count=1,
                item_names=None,
                required_references=(),
            ),
            {},
            contract_drift=drift,
        )

        self.assertEqual(drift["added_categories"], ["Runes"])
        self.assertEqual(drift["removed_categories"], ["Currency"])
        self.assertEqual(drift["added_fields"], ["lines.new", "root.items"])
        self.assertEqual(drift["removed_fields"], ["lines.old"])
        self.assertEqual(entry["status"], "partial")
        self.assertIn("contract_drift", entry["status_reasons"])

    def test_poecurrency_adapter_uses_fixture_without_network(self):
        payload = [
            {
                "category_label": "通货仓库",
                "items": [
                    {
                        "item_name": "神圣石",
                        "engname": "Divine Orb",
                        "currency_unit": "e",
                        "latest_buy1": 500,
                    },
                    {
                        "item_name": "崇高石",
                        "engname": "Exalted Orb",
                        "currency_unit": "e",
                        "latest_buy1": 1,
                    },
                ],
            }
        ]

        class FixtureClient:
            def get_json(self, url):
                self.requested = url
                return payload

            def latest_http(self, _predicate):
                return {
                    "url": "https://poecurrency.top/api/summary?version=2",
                    "status_code": 200,
                    "content_type": "application/json",
                    "content_bytes": 256,
                }

        client = FixtureClient()
        result = self.audit.audit_poecurrency(client, self.league(), None, 1)

        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["metrics"]["price_items"], 2)
        self.assertIn("engname", result["metrics"]["field_sets"]["item"])
        self.assertEqual(
            client.requested, self.audit.builder.DEFAULT_POECURRENCY_SUMMARY_API
        )

    def test_baseline_lookup_and_utf8_report_output(self):
        entry = self.source_entry("source")
        baseline = {"sources": {"source": entry}}
        schema = self.audit._baseline_schema(baseline, "source")
        self.assertEqual(schema["digest"], entry["health"]["schema"]["digest"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "审计.json"
            report = {"message": "实时数据", "sources": {}}
            self.audit.write_report(path, report)
            raw = path.read_bytes()
            self.assertTrue(raw.endswith(b"\n"))
            self.assertEqual(json.loads(raw.decode("utf-8")), report)

    def test_committed_compact_baseline_is_used_by_scheduled_workflow(self):
        baseline = self.audit.load_baseline(BASELINE_PATH)
        self.assertEqual(
            set(baseline["sources"]),
            {"poe2scout", "poe.ninja", "poecurrency.top", "poe2db"},
        )
        for contract in baseline["sources"].values():
            self.assertTrue(contract["categories"])
            self.assertTrue(contract["field_sets"])
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("--baseline", workflow)
        self.assertIn("data_source_contract_baseline.json", workflow)
        self.assertIn("contents: read", workflow)


if __name__ == "__main__":
    unittest.main()
