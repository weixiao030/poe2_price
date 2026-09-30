"""Tablet markets follow the current season without changing ordinary prices."""
import json
import struct
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from tests.test_tablet_affixes import synthetic_baseitems, csd, game_tables, page, quote, LEAGUE, m
from tests.test_tablet_cn import cn_page, LEAGUE as CN_LEAGUE
from tests.test_whole_tablets import page as whole_page, row as whole_row, words_fixture
from tests.test_cn_historical_prices import snapshot
import build_poe2scout_price_patch as builder
import poe2_name_price_patch as name_patch


def directory(server):
    latest = CN_LEAGUE if server == 'cn' else LEAGUE
    return dict(server=server, stale=False, default=latest, data=[
        dict(name='Runes of Aldur', hardcore=False),
        dict(name=latest, hardcore=False, current=True),
    ])


@pytest.mark.parametrize('server', ['cn', 'international'])
@pytest.mark.parametrize('ordinary', [False, True])
@pytest.mark.parametrize('names,affixes', [(True, True), (True, False), (False, True), (False, False)])
def test_builder_uses_latest_for_every_tablet_layer(tmp_path, monkeypatch, server, names, affixes, ordinary):
    latest = CN_LEAGUE if server == 'cn' else LEAGUE
    requests = []

    class Client:
        def __init__(self, **kwargs): pass

        def get_json(self, url):
            requests.append(url)
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            if 'poecurrency.top' in url:
                assert ordinary, 'tablet-only builds must not depend on ordinary prices'
                assert query['season'] == ['RunesofAldur']
                payload = snapshot(stale=False)
                payload[0]['items'].append(dict(
                    item_name='行情物品', engname='Market Item', currency_unit='e', latest_buy1=7,
                    latest_datetime=payload[0]['items'][0]['latest_datetime']))
                return payload
            if parsed.path.endswith('/leagues'):
                assert query['league'] == ['auto']
                assert query['server'] == [server]
                return directory(server)
            assert query['league'] == [latest], 'tablet request must ignore historical selection'
            if parsed.path.endswith('/currencies'):
                return dict(server=server, league=latest, primary='exalted', stale=False,
                            values=dict(exalted=1, chaos=50, divine=500))
            if 'poe.ninja' in url:
                assert names
                if query['type'] == ['UniqueTablets']:
                    return dict(core=dict(primary='divine', rates=dict(exalted=500, chaos=10)),
                                lines=[dict(name='Freedom of Faith', primaryValue=2, listingCount=10)])
                assert query['type'] == ['PrecursorTablets']
                return dict(core=dict(primary='divine', rates=dict(exalted=500, chaos=10)),
                            lines=[dict(baseType='Ritual Tablet', variant='Normal', primaryValue=.5,
                                        listingCount=10, corrupted=False)])
            if parsed.path.endswith('/whole-tablets/prices'):
                assert names and server == 'cn'
                return whole_page([whole_row(), whole_row('unique')])
            assert parsed.path.endswith('/prices') and affixes
            rarity = query['rarity'][0]
            return cn_page(rarity) if server == 'cn' else page([quote()], rarity=rarity)

        def request_metrics(self): return []

    def ordinary_prices(source, client, args, **kwargs):
        assert ordinary, 'tablet-only builds must not depend on ordinary prices'
        assert args.league == 'runes' and args.poe_ninja_league == 'Runes of Aldur'
        assert args.league_is_current == 'false'
        prices = {'divine': builder.PriceObservation('divine', 'Divine Orb', 'Currency', Decimal(200), Decimal(10), 'old'),
                  'exalted': builder.PriceObservation('exalted', 'Exalted Orb', 'Currency', Decimal(1), Decimal(10), 'old'),
                  'market-item': builder.PriceObservation('market-item', 'Market Item', 'Currency', Decimal(7), Decimal(10), 'old')}
        return builder.PriceSourceResult(source, raw={}, prices=prices, status='ok', health={})

    monkeypatch.setattr(builder, 'RetryingRequests', Client)
    monkeypatch.setattr(builder, 'try_fetch_price_source', ordinary_prices)
    if not ordinary:
        def no_ordinary_discovery(*args, **kwargs):
            raise AssertionError('tablet-only builds must use only the tablet league directory')
        monkeypatch.setattr(builder, 'resolve_current_leagues', no_ordinary_discovery)
    def baseitems(english):
        raw = synthetic_baseitems(english)
        entries = name_patch.scan_base_item_names(raw)
        replacements, warnings = name_patch.build_replacements(entries, [dict(
            metadata_path=entries[-1].metadata_path,
            new_name='Market Item' if english else '行情物品')], '=', False, 'append', False)
        assert warnings == []
        return name_patch.apply_replacements_append(raw, replacements)

    source = tmp_path / 'source.dat'; source.write_bytes(baseitems(False))
    english = tmp_path / 'english.dat'; english.write_bytes(baseitems(True))
    words = tmp_path / 'words.dat'; words_fixture(words)
    gold = tmp_path / 'unique-gold.dat'
    gold_data = bytearray(4 + builder.UNIQUE_GOLD_PRICES_ROW_SIZE)
    struct.pack_into('<I', gold_data, 0, 1)
    gold.write_bytes(gold_data)
    template = tmp_path / 'template.it'
    template.write_text('Mods\n{\nstat_description_list = "Data/StatDescriptions/tablet_stat_descriptions.csd"\n}\n', encoding='utf-8')
    descriptions = tmp_path / 'tablet.csd'; descriptions.write_bytes(csd().encode('utf-8'))
    arguments = [
        '--price-source', 'poecurrency-cn' if server == 'cn' else 'poe2scout',
        '--league', 'runes', '--poe-ninja-league', 'Runes of Aldur',
        '--league-is-current', 'false', '--tablet-cn-season', 'RunesofAldur',
        '--poecurrency-summary-url', 'https://poecurrency.top/api/summary?version=2&season=RunesofAldur',
        '--cn-reference-source', 'none', '--fallback-price-sources', 'none',
        '--patch-scope', 'currency' if ordinary else 'none', '--out-dir', str(tmp_path / 'out'),
        '--en-baseitems', str(english), '--tc-baseitems', str(source),
        '--en-words', str(words), '--tc-words', str(words), '--unique-gold-prices', str(gold),
        '--patched-dat', str(tmp_path / 'patched.dat'),
        '--game-path', 'data/balance/traditional chinese/baseitemtypes.datc64',
        '--tablet-template-it', str(template), '--tablet-template-csd', str(descriptions),
    ]
    if ordinary:
        arguments.extend(['--resolved-leagues', '--no-uniques'])
    for key, value in game_tables(tmp_path).items():
        arguments.extend(['--' + key.replace('_', '-'), str(value)])
    if not names: arguments.append('--no-tablet-prices')
    if not affixes: arguments.append('--no-tablet-affixes')
    assert builder.main(arguments) == 0
    report = json.loads((tmp_path / 'out/summary.json').read_text(encoding='utf-8'))
    assert report['poe_ninja_league'] == 'Runes of Aldur'
    assert report['league_is_current'] is False
    if names or affixes:
        assert report['tablet_market']['league'] == latest
        assert report['tablet_market']['display_rates_exalted']['divine'] == '500'
    elif not ordinary:
        assert requests == []
    if names:
        assert report['whole_tablets']['league'] == latest
        assert report['whole_tablets']['base_names']
        assert report['whole_tablets']['unique_prices']
    if ordinary:
        # The regular market still keeps the old season's rate.
        assert Decimal(report['display_rates_exalted']['divine']) == (300 if server == 'cn' else 200)
    else:
        assert report['display_rates_exalted'] == {}
        assert report['price_items'] == 0
        assert report['unique_words_patched'] == int(names)
    if affixes:
        assert report['tablet_affixes']['league'] == latest
        assert report['tablet_affixes']['resources']
    else:
        assert report['tablet_affixes']['status'] == 'disabled'


@pytest.mark.parametrize('available', [True, False])
def test_international_unique_tablets_replace_or_remove_historical_prices(tmp_path, available):
    source, output = tmp_path / 'words.dat', tmp_path / 'patched.dat'
    words_fixture(source, '[99D|字体补丁译名]')
    name = 'Freedom of Faith'
    prices = {'unique:freedomoffaith': builder.PriceObservation(
        'unique:freedomoffaith', name, 'UniqueTablets', Decimal(10000), Decimal(10), 'old', '99D')}
    override = dict(name_en=name, price='2D', amount='2', trade_url='latest') if available else None
    count, rows, _ = builder.patch_unique_word_prices(source,
        {'freedomoffaith': builder.UniqueName(0, name, '字体补丁译名')}, prices, output,
        tablet_prices={name.casefold(): override})
    raw = output.read_bytes()
    assert builder.read_words_row(raw, builder.detect_words_layout(raw), 0).display_name == (
        '[2D|字体补丁译名]' if available else '字体补丁译名')
    assert count == int(available)
    assert prices['unique:freedomoffaith'].display_price == '99D', 'ordinary observations are not mutated'


@pytest.mark.parametrize('mutation', ['server', 'stale', 'hardcore', 'archived', 'default'])
def test_latest_directory_never_falls_back_to_another_market_or_old_season(mutation):
    payload = directory('cn')
    if mutation == 'server': payload['server'] = 'international'
    elif mutation == 'stale': payload['stale'] = True
    elif mutation == 'default': payload['default'] = 'missing'
    else: payload['data'][1][mutation] = True
    class Client:
        def get_json(self, url): return payload
    with pytest.raises(ValueError):
        m.resolve_latest_tablet_league(Client(), 'http://test.invalid', 'cn')


def test_tablet_rates_reject_historical_season():
    class Client:
        def get_json(self, url):
            return dict(server='cn', league='奥杜尔秘符', primary='exalted', stale=False,
                        values=dict(exalted=1, divine=999, chaos=50))
    with pytest.raises(ValueError, match='最新赛季'):
        m.fetch_tablet_display_rates(Client(), 'http://test.invalid', CN_LEAGUE, 'cn')
