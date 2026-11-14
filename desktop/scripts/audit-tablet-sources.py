"""Read-only contract audit of both tablet markets using production adapters."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '物价补丁/tools'))
from build_poe2scout_price_patch import DEFAULT_TABLET_API_BASE
from price_sources.http_client import RetryingRequests
from poe2_tablet_prices import (
    fetch_tablet_affix_prices, fetch_tablet_display_rates,
    resolve_latest_tablet_league, fetch_poe_ninja_precursor_tablets,
)
from poe2_whole_tablets import fetch_cn_whole_tablets


def audit_market(server, api_base):
    client = RetryingRequests(max_retries=1, timeout=30, total_timeout=90)
    report = {'server': server, 'layers': {}}
    try:
        league = resolve_latest_tablet_league(client, api_base, server)
        report['league'] = league
        rates, rate_report = fetch_tablet_display_rates(client, api_base, league, server)
        report['exchange_rates'] = rate_report
    except Exception as exc:
        report.update(status='unavailable', error=f'{type(exc).__name__}: {exc}')
        return report
    for rarity in ('magic', 'rare'):
        try:
            rows, metadata = fetch_tablet_affix_prices(
                client, api_base, league, rarity=rarity, server=server,
                allow_stale=False, allow_stale_snapshot=False,
            )
            report['layers'][rarity] = {
                'status': 'ok' if rows else 'empty', 'rows': len(rows),
                **{key: metadata.get(key) for key in ('total', 'pages', 'partial_snapshot')},
            }
        except Exception as exc:
            report['layers'][rarity] = {'status': 'unavailable', 'error': f'{type(exc).__name__}: {exc}'}
    name = 'whole-tablets' if server == 'cn' else 'precursor-tablets'
    try:
        if server == 'cn':
            result = fetch_cn_whole_tablets(client, api_base, league, allow_stale=False, exchange_rates=rates)
            report['layers'][name] = {
                'status': result['status'], 'rows': result['rows'],
                'pages': result['pages'], 'skipped': len(result['skipped']),
            }
        else:
            result = fetch_poe_ninja_precursor_tablets(client, league, display_rates=rates)
            report['layers'][name] = {'status': 'ok', 'rows': result['usable_lines']}
    except Exception as exc:
        report['layers'][name] = {'status': 'unavailable', 'error': f'{type(exc).__name__}: {exc}'}
    report['status'] = 'ok' if all(row['status'] in {'ok', 'partial'} for row in report['layers'].values()) else 'unavailable'
    report['http'] = client.request_metrics()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'desktop/test-results/tablet-source-audit.json')
    parser.add_argument('--api-base', default=DEFAULT_TABLET_API_BASE)
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=2) as pool:
        markets = list(pool.map(lambda server: audit_market(server, args.api_base), ('international', 'cn')))
    report = {
        'checked_at': datetime.now(timezone.utc).isoformat(), 'read_only': True,
        'freshness_policy': 'fresh-only audit; production may retain same-season stale snapshots with timestamps',
        'markets': markets,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for market in markets:
        print(json.dumps({key: value for key, value in market.items() if key != 'http'}, ensure_ascii=False))
    return int(any(market['status'] != 'ok' for market in markets))


if __name__ == '__main__':
    raise SystemExit(main())
