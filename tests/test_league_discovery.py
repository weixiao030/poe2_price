import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "物价补丁"
    / "tools"
    / "price_sources"
    / "league.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("league_discovery", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return self.payload


class LeagueDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.league = load_module()

    def test_selects_current_softcore_when_softcore_and_hardcore_are_current(self):
        client = FakeClient(
            [
                {"Value": "Runes of Aldur", "ShortName": "runes", "IsCurrent": True},
                {"Value": "HC Runes of Aldur", "ShortName": "runeshc", "IsCurrent": True},
                {"Value": "Fate of the Vaal", "ShortName": "vaal", "IsCurrent": False},
            ]
        )

        selected = self.league.resolve_current_leagues(
            client, "https://api.poe2scout.com/"
        )

        self.assertEqual(selected.scout, "runes")
        self.assertEqual(selected.poe_ninja, "Runes of Aldur")
        self.assertEqual(selected.source, "auto")
        self.assertFalse(selected.used_fallback)
        self.assertEqual(client.urls, ["https://api.poe2scout.com/poe2/Leagues"])

    def test_discovers_all_softcore_options_with_current_first(self):
        client = FakeClient(
            [
                {"Value": "Old League", "ShortName": "old", "IsCurrent": False},
                {"Value": "HC Current", "ShortName": "currenthc", "IsCurrent": True},
                {"Value": "Current League", "ShortName": "current", "IsCurrent": True},
                {"Value": "Old League", "ShortName": "old", "IsCurrent": False},
            ]
        )

        options = self.league.discover_league_options(
            client, "https://api.poe2scout.com"
        )

        self.assertEqual(
            [(item.scout, item.poe_ninja, item.is_current) for item in options],
            [("current", "Current League", True), ("old", "Old League", False)],
        )
        self.assertEqual(client.urls, ["https://api.poe2scout.com/poe2/Leagues"])

    def test_discovers_poe1_pc_realm_without_reusing_poe2_realm(self):
        client = FakeClient(
            [{"Value": "PC League", "ShortName": "pc-league", "IsCurrent": True}]
        )

        options = self.league.discover_realm_league_options(
            client, "https://api.poe2scout.com", "pc"
        )

        self.assertEqual(options[0].scout, "pc-league")
        self.assertEqual(client.urls, ["https://api.poe2scout.com/pc/Leagues"])

    def test_accepts_wrapped_response_and_field_aliases(self):
        client = FakeClient(
            {
                "data": [
                    {
                        "name": "Future League",
                        "short_name": "future",
                        "is_current": "true",
                        "is_hardcore": False,
                    },
                    {
                        "name": "HC Future League",
                        "short_name": "futurehc",
                        "is_current": 1,
                        "is_hardcore": True,
                    },
                ]
            }
        )

        selected = self.league.resolve_current_leagues(client, "https://example.invalid")

        self.assertEqual((selected.scout, selected.poe_ninja), ("future", "Future League"))
        self.assertEqual(selected.warnings, ())

    def test_both_explicit_values_skip_discovery(self):
        client = FakeClient(error=AssertionError("must not request"))

        selected = self.league.resolve_current_leagues(
            client,
            "https://example.invalid",
            explicit_scout=" custom-scout ",
            explicit_ninja=" Custom Ninja ",
        )

        self.assertEqual((selected.scout, selected.poe_ninja), ("custom-scout", "Custom Ninja"))
        self.assertEqual(selected.source, "explicit")
        self.assertEqual(client.urls, [])

    def test_partial_explicit_value_overrides_only_its_provider(self):
        client = FakeClient(
            [{"value": "New League", "shortName": "new", "current": True}]
        )

        selected = self.league.resolve_current_leagues(
            client,
            "https://example.invalid/",
            explicit_scout="manual",
        )

        self.assertEqual(selected.scout, "manual")
        self.assertEqual(selected.poe_ninja, "New League")
        self.assertEqual(selected.source, "explicit+auto")

    def test_request_failure_uses_known_good_defaults(self):
        client = FakeClient(error=TimeoutError("deadline"))

        selected = self.league.resolve_current_leagues(client, "https://example.invalid")

        self.assertEqual(selected.scout, "runes")
        self.assertEqual(selected.poe_ninja, "Runes of Aldur")
        self.assertEqual(selected.source, "fallback")
        self.assertTrue(selected.used_fallback)
        self.assertEqual(len(selected.warnings), 1)
        self.assertIn("deadline", selected.warnings[0])

    def test_partial_explicit_value_survives_discovery_failure(self):
        selected = self.league.resolve_current_leagues(
            FakeClient(payload={"unexpected": []}),
            "https://example.invalid",
            explicit_ninja="Manual Ninja",
        )

        self.assertEqual(selected.scout, "runes")
        self.assertEqual(selected.poe_ninja, "Manual Ninja")
        self.assertEqual(selected.source, "explicit+fallback")

    def test_bad_schema_variants_fail_closed_to_defaults(self):
        payloads = (
            None,
            "not-json-object",
            {},
            {"data": [{"Value": "Old", "ShortName": "old", "IsCurrent": False}]},
            {"data": [{"Value": "Missing Short Name", "IsCurrent": True}]},
            {
                "data": [
                    {"Value": "League One", "ShortName": "one", "IsCurrent": True},
                    {"Value": "League Two", "ShortName": "two", "IsCurrent": True},
                ]
            },
        )

        for payload in payloads:
            with self.subTest(payload=payload):
                selected = self.league.resolve_current_leagues(
                    FakeClient(payload=payload), "https://example.invalid"
                )
                self.assertEqual(
                    (selected.scout, selected.poe_ninja),
                    ("runes", "Runes of Aldur"),
                )
                self.assertEqual(selected.source, "fallback")
                self.assertEqual(len(selected.warnings), 1)

    def test_duplicate_identical_softcore_rows_are_not_ambiguous(self):
        row = {"Value": "Runes of Aldur", "ShortName": "runes", "IsCurrent": True}
        selected = self.league.resolve_current_leagues(
            FakeClient(payload=[row, dict(row)]), "https://example.invalid"
        )

        self.assertEqual((selected.scout, selected.poe_ninja), ("runes", "Runes of Aldur"))
        self.assertEqual(selected.source, "auto")

    def test_explicit_hardcore_flag_takes_priority_over_name_heuristic(self):
        client = FakeClient(
            [
                {
                    "Value": "HC-like Softcore Name",
                    "ShortName": "softcorehc",
                    "IsCurrent": True,
                    "IsHardcore": False,
                },
                {
                    "Value": "Hardcore Other",
                    "ShortName": "other",
                    "IsCurrent": True,
                    "IsHardcore": True,
                },
            ]
        )

        selected = self.league.resolve_current_leagues(client, "https://example.invalid")

        self.assertEqual(
            (selected.scout, selected.poe_ninja),
            ("softcorehc", "HC-like Softcore Name"),
        )

    def test_dynamic_options_keep_provider_ids_paired_per_season(self):
        client = FakeClient(
            [
                {"Value": "Season One", "ShortName": "one", "IsCurrent": False},
                {"Value": "Season Two", "ShortName": "two", "IsCurrent": True},
            ]
        )

        options = self.league.discover_league_options(client, "https://example.invalid")

        self.assertEqual(
            [(item.scout, item.poe_ninja) for item in options],
            [("two", "Season Two"), ("one", "Season One")],
        )


if __name__ == "__main__":
    unittest.main()
