"""Selected-season snapshots remain usable without inventing a Divine rate."""
import csv
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '物价补丁' / 'tools'))
import build_poe2scout_price_patch as builder


def snapshot(*, conflicting_rate=False, stale=True):
    stamp = '2020-01-01 12:00:00' if stale else datetime.now(timezone.utc).isoformat()
    items = [
        dict(item_name='神圣石', engname='Divine Orb', currency_unit='e',
             latest_buy1=9999 if conflicting_rate else 300, latest_sell1=1750 if conflicting_rate else 300,
             buy_avg=9999 if conflicting_rate else 300, sell_avg=1716 if conflicting_rate else 300,
             buy_avg_yesterday=7227 if conflicting_rate else 300, sell_avg_yesterday=1838 if conflicting_rate else 300),
        dict(item_name='混沌石', engname='Chaos Orb', currency_unit='e', latest_buy1=10),
        dict(item_name='D 物品', engname='D Item', currency_unit='d', latest_buy1=2.3456),
        dict(item_name='E 物品', engname='E Item', currency_unit='e', latest_buy1=25),
        *[dict(item_name=f'物品 {i}', engname=f'Item {i}', currency_unit='e', latest_buy1=3) for i in range(30)],
    ]
    return [dict(category_label='通货仓库', items=[dict(row, latest_datetime=stamp) for row in items])]


def run_builder(tmp_path, monkeypatch, payload, current):
    endpoint = 'https://poecurrency.top/api/summary?version=2'
    if not current:
        endpoint += '&season=RunesofAldur'
    requests = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def get_json(self, url):
            requests.append(url)
            assert url == endpoint, 'must not query another league or an international rate'
            return payload

        def request_metrics(self):
            return []

    monkeypatch.setattr(builder, 'RetryingRequests', Client)
    monkeypatch.setattr(builder, 'load_base_item_pairs', lambda *args: [
        builder.BaseItemPair(f'Metadata/Items/{i}', row['engname'], row['item_name'])
        for i, row in enumerate(payload[0]['items'])
    ] if payload else [])
    en = tmp_path / 'en.dat'
    en.touch()
    result = builder.main([
        '--price-source', 'poecurrency-cn', '--poecurrency-summary-url', endpoint,
        '--resolved-leagues', '--league-is-current', str(current).lower(),
        '--cn-reference-source', 'none', '--fallback-price-sources', 'none',
        '--patch-scope', 'currency', '--no-uniques', '--no-tablet-prices',
        '--no-tablet-affixes', '--no-build-patch', '--en-baseitems', str(en),
        '--tc-baseitems', str(tmp_path / 'tc.dat'), '--out-dir', str(tmp_path),
    ])
    assert result == 0
    assert requests == [endpoint]
    report = json.loads((tmp_path / 'summary.json').read_text(encoding='utf-8'))
    with (tmp_path / 'matched_prices_detail.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = {row['name']: row for row in csv.DictReader(f)}
    return report, rows


@pytest.mark.parametrize('current', [False, True])
@pytest.mark.parametrize('conflicting_rate', [False, True])
def test_stale_snapshot_builds_for_selected_season(tmp_path, monkeypatch, capsys, current, conflicting_rate):
    report, rows = run_builder(tmp_path, monkeypatch, snapshot(conflicting_rate=conflicting_rate), current)
    assert report['league_is_current'] is current
    assert report['primary_source_status'] == 'partial'
    assert report['poecurrency_quality']['stale_ratio'] == 1
    assert report['source_health']['poecurrency-cn']['state'] == 'stale'
    assert rows['D 物品']['price'] == '2.34D'
    assert rows['E 物品']['price'] == '2.5C'
    assert report['fallback_matched_items'] == 0
    assert '2020-01-01' in capsys.readouterr().out
    if conflicting_rate:
        assert report['divine_price_exalted'] == '0'
        assert report['divine_exalted_ratio']['exalted_orb'] == ''
        assert rows['D 物品']['price_exalted'] == '0'
        assert 'd_native_no_exchange_rate' in rows['D 物品']['source_pair']
        assert '汇率缺失或报价冲突' in report['primary_source_warning']
    else:
        assert report['divine_price_exalted'] == '300'
        assert Decimal(rows['D 物品']['price_exalted']) == Decimal('703.68')


def test_fresh_snapshot_retains_current_pricing(tmp_path, monkeypatch):
    report, rows = run_builder(tmp_path, monkeypatch, snapshot(stale=False), True)
    assert report['primary_source_status'] == 'ok'
    assert report['primary_source_warning'] == ''
    assert report['poecurrency_quality']['stale_ratio'] == 0
    assert rows['D 物品']['price'] == '2.34D'


@pytest.mark.parametrize('invalid', ['empty', 'units', 'prices'])
def test_age_relaxation_does_not_accept_invalid_prices(tmp_path, monkeypatch, invalid):
    payload = snapshot()
    if invalid == 'empty':
        payload = []
    elif invalid == 'units':
        for row in payload[0]['items']:
            del row['currency_unit']
    else:
        for row in payload[0]['items']:
            for key in list(row):
                if key.startswith(('latest_buy', 'latest_sell', 'buy_avg', 'sell_avg')):
                    row[key] = 0
    with pytest.raises(ValueError):
        run_builder(tmp_path, monkeypatch, payload, False)
    assert not (tmp_path / 'summary.json').exists()
    assert not (tmp_path / 'prices.csv').exists()


def test_native_d_is_not_converted_with_unverified_derived_exalted_price():
    payload = snapshot(conflicting_rate=True)
    payload[0]['items'][2]['e'] = 999999
    prices, quality = builder.collect_poecurrency_observations_with_quality(payload)
    obs = prices[builder.poecurrency_api_id('D 物品')]
    assert 'divine' not in prices
    assert obs.price_exalted == 0
    assert obs.native_price == Decimal('2.3456')
    assert 'explicit_price_rejected' in obs.quality_flags
    builder.apply_display_prices(prices, Decimal(0))
    assert obs.display_price == '2.34D'
    assert builder.has_name_price(obs)
    assert not quality['divine_rate_available']


def test_native_d_unique_does_not_fall_back_to_international_price(tmp_path):
    from tests.test_whole_tablets import words_fixture
    source, output = tmp_path / 'words.dat', tmp_path / 'patched.dat'
    words_fixture(source, 'D 物品')
    prices, _ = builder.collect_poecurrency_observations_with_quality(snapshot(conflicting_rate=True))
    builder.apply_display_prices(prices, Decimal(0))
    names = {'ditem': builder.UniqueName(0, 'D Item', 'D 物品')}
    international = {'unique:ditem': builder.PriceObservation(
        'unique:ditem', 'D Item', 'UniqueArmours', Decimal(99999), Decimal(1), 'international', '99D')}
    count, rows, _, fallback = builder.patch_unique_word_prices_with_cn_fallback(
        source, names, prices, international, output)
    assert count == 1 and fallback == 0
    assert rows[0]['price'] == '2.34D'
    assert builder.read_words_row(output.read_bytes(), builder.detect_words_layout(output.read_bytes()), 0).display_name == '[2.34D|D 物品]'


def test_missing_divine_row_still_preserves_direct_quotes(tmp_path, monkeypatch):
    payload = snapshot()
    payload[0]['items'].pop(0)
    report, rows = run_builder(tmp_path, monkeypatch, payload, False)
    assert rows['D 物品']['price'] == '2.34D'
    assert rows['E 物品']['price'] == '2.5C'
    assert not report['poecurrency_quality']['divine_rate_available']


def test_failed_full_and_core_build_logs_survive_stage_cleanup(tmp_path):
    from tests.test_game_directory_selection import ps_quote, run_powershell
    script = (Path(__file__).resolve().parents[1] / '物价补丁/tools/update_price_patch.ps1').read_text(encoding='utf-8-sig')
    start = script.index('    New-Item -ItemType Directory -Force -Path $BuildStageDir | Out-Null', script.index('$WholeTabletLayerStatus ='))
    end = script.index('    Assert-File $StagePatchZip', start)
    finally_start = script.index('finally {\n    if (Test-Path -LiteralPath $BuildStageDir', end)
    finally_end = script.index('\n\nWrite-Host', finally_start)
    result = run_powershell(f"""
        $ErrorActionPreference='Stop'
        $BuildStageDir=Join-Path {ps_quote(tmp_path)} '.price-build-test'
        $StagePriceBuildLog=Join-Path $BuildStageDir 'price_patch_build.log'
        $PriceBuildLog=Join-Path {ps_quote(tmp_path)} 'price_patch_build.log'
        $CanPatchUniqueWords=$true
        $BuildArgs=@('full')
        function Get-CoreOnlyPriceBuildArgs {{ @('core') }}
        function Invoke-Poe2Python {{
            param($Python, $ArgumentList)
            [pscustomobject]@{{ ExitCode=1; Text="failure: $ArgumentList" }}
        }}
        try {{
            {script[start:end]}
        }} catch {{
            if (-not $_.Exception.Message.Contains($PriceBuildLog)) {{ throw 'wrong log path' }}
        }} {script[finally_start:finally_end]}
        if (Test-Path -LiteralPath $BuildStageDir) {{ throw 'stage still exists' }}
        Get-Content -LiteralPath $PriceBuildLog -Raw -Encoding UTF8
    """)
    assert 'failure: full' in result
    assert 'failure: core' in result
