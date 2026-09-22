"""Read-only source audit using the leagues observed through the packaged app."""

import json
import argparse
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', nargs='+', help='Recheck selected sources after a network or configuration failure')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    evidence = json.loads((ROOT / "desktop/test-results/compatibility-evidence.json").read_text(encoding="utf-8"))
    observed = {(item["gameVersion"], item["china"]): next(league for league in item["leagues"]
                if league["IsCurrent"] and not league.get("DiscoveryFallback")) for item in evidence["leagues"]}
    assert len(observed) == 4, "Run verify-compatibility.mjs --live first"
    current = observed[("poe2", False)]
    selection = LeagueSelection(scout=current["ScoutLeague"], poe_ninja=current["PoeNinjaLeague"], source="explicit")
    for game, module in [('poe2', audit.builder), ('poe1', audit.poe1_builder)]:
        selected = observed[(game, True)]
        if not selected['IsCurrent']:
            module.DEFAULT_POECURRENCY_SUMMARY_API = seasonal_url(module.DEFAULT_POECURRENCY_SUMMARY_API, selected['PoeCurrencySeason'])
    client = audit.RecordingClient(audit.builder.RetryingRequests(max_retries=1, timeout=20, total_timeout=45))
    auditors = audit.DEFAULT_AUDITORS
    if args.sources:
        auditors = tuple(item for item in auditors if item[0] in args.sources)
        assert len(auditors) == len(set(args.sources)), 'Unknown source name'
    report = audit.run_audit(client, max_workers=3, league_resolver=lambda *_args: selection, auditors=auditors)
    report["selected_desktop_leagues"] = evidence["leagues"]
    destination = args.output or ROOT / "desktop/test-results/selected-source-audit.json"
    audit.write_report(destination, report)
    assert not report["league"]["used_fallback"]
    assert not report["overall"]["failed_sources"], report["overall"]
    assert all(item["health"]["usable"] for item in report["sources"].values())
    print(json.dumps({"report": str(destination), "overall": report["overall"], "league": report["league"],
        "sources": {name: {"status": item["status"], "usable": item["health"]["usable"], "items": item["health"]["counts"]["items"], "issues": item["health"]["issues"]} for name, item in report["sources"].items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
