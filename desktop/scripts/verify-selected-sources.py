"""Read-only source audit using the leagues observed through the packaged app."""

import json
from pathlib import Path
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "物价补丁" / "tools"))
import audit_price_sources as audit
from price_sources.league import LeagueSelection


def seasonal_url(url, season):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query["season"] = season
    return urlunsplit(parts._replace(query=urlencode(query)))


def main():
    evidence = json.loads((ROOT / "desktop/test-results/compatibility-evidence.json").read_text(encoding="utf-8"))
    observed = {(item["gameVersion"], item["china"]): item["leagues"][0] for item in evidence["leagues"]}
    assert len(observed) == 4, "Run verify-compatibility.mjs --live first"
    current = observed[("poe2", False)]
    selection = LeagueSelection(scout=current["ScoutLeague"], poe_ninja=current["PoeNinjaLeague"], source="explicit", discovery_url=current["DiscoveryUrl"])
    audit.builder.DEFAULT_POECURRENCY_SUMMARY_API = seasonal_url(audit.builder.DEFAULT_POECURRENCY_SUMMARY_API, observed[("poe2", True)]["PoeCurrencySeason"])
    audit.poe1_builder.DEFAULT_POECURRENCY_SUMMARY_API = seasonal_url(audit.poe1_builder.DEFAULT_POECURRENCY_SUMMARY_API, observed[("poe1", True)]["PoeCurrencySeason"])
    client = audit.RecordingClient(audit.builder.RetryingRequests(max_retries=1, timeout=20, total_timeout=45))
    report = audit.run_audit(client, max_workers=3, league_resolver=lambda *_args: selection)
    report["selected_desktop_leagues"] = evidence["leagues"]
    destination = ROOT / "desktop/test-results/selected-source-audit.json"
    audit.write_report(destination, report)
    assert not report["league"]["used_fallback"]
    assert not report["overall"]["failed_sources"], report["overall"]
    assert all(item["health"]["usable"] for item in report["sources"].values())
    print(json.dumps({"report": str(destination), "overall": report["overall"], "league": report["league"],
        "sources": {name: {"status": item["status"], "usable": item["health"]["usable"], "items": item["health"]["counts"]["items"], "issues": item["health"]["issues"]} for name, item in report["sources"].items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
