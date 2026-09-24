"""CN market isolation, live pagination and currency conversion regressions."""
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import quote as urlquote

import pytest
from tests.test_tablet_affixes import Client, page, quote, trade_url, m

LEAGUE = '周年庆巅峰挑战'


def cn_page(rarity='rare', offset=0, total=1):
    identity = dict(server='cn', category='tablet', rarity=rarity, league=LEAGUE)
    row = dict(quote(str(offset), price=500), **identity)
    row['trade_url'] = trade_url(str(offset), rarity).replace('www.pathofexile.com', 'poe.game.qq.com').replace('Forbidden%20Rites', urlquote(LEAGUE))
    payload = page([row], offset=offset, total=total, rarity=rarity)
    payload.update(**identity, scope=identity, snapshot=None, view='live')
    payload['partial_snapshot'] = dict(identity, id='cn-run', revision=42,
        last_batch_at=datetime.now(timezone.utc).isoformat())
    payload['exchange_rates'] = dict(server='cn', league=LEAGUE, id='rates', primary='exalted',
        stale=False, values={'exalted':1, 'divine':500, 'chaos':100})
    return payload


def test_cn_uses_local_trade_query_and_divine_normalized_rates():
    prices = {}; reports = {}
    for rarity in ('magic', 'rare'):
        client = Client({0: cn_page(rarity)})
        prices[rarity], reports[rarity] = m.fetch_tablet_affix_prices(client, 'http://test.invalid', LEAGUE, rarity=rarity, server='cn')
        assert 'server=cn' in client.urls[0] and 'view=live' in client.urls[0]
        assert Decimal(reports[rarity]['rates']['exalted']) == Decimal('0.002')
        assert Decimal(reports[rarity]['rates']['chaos']) == Decimal('0.2')
    pairs, audit = m.pair_tablet_quotes(prices, reports)
    assert pairs['Ritual_Tablet']
    assert Decimal(audit[0]['rare_divine']) == 1
    assert Decimal(audit[0]['magic_divine']) == 1
    assert 'poe.game.qq.com' in prices['rare']['Ritual_Tablet'][0].query_scope


@pytest.mark.parametrize('section,key,value', [
    ('scope', 'server', 'international'), ('exchange_rates', 'server', 'international'),
    ('exchange_rates', 'league', 'Forbidden Rites'), ('partial_snapshot', 'server', 'international'),
    ('partial_snapshot', 'rarity', 'magic'), ('partial_snapshot', 'league', 'Forbidden Rites'),
    ('partial_snapshot', 'revision', 43), ('exchange_rates', 'id', 'new-rates'),
])
def test_cn_rejects_mixed_markets_and_live_revision_changes(section, key, value):
    first = cn_page(total=2); second = cn_page(offset=1, total=2)
    second[section][key] = value
    with pytest.raises(ValueError):
        m.fetch_tablet_affix_prices(Client({0:first, 1:second}), 'http://test.invalid', LEAGUE, server='cn')


def test_cn_cannot_reuse_international_cache_or_queries(tmp_path):
    international = page([quote()])
    m.fetch_tablet_affix_prices(Client({0:international}), 'http://test.invalid', 'Forbidden Rites', cache_dir=tmp_path)
    with pytest.raises(ValueError):
        m.fetch_tablet_affix_prices(Client({0:international}), 'http://test.invalid', 'Forbidden Rites', server='cn', cache_dir=tmp_path)
    assert not m.trade_query_scope(trade_url('one', 'rare'), 'rare', 'cn')
    m.fetch_tablet_affix_prices(Client({0:cn_page()}), 'http://test.invalid', LEAGUE, server='cn', cache_dir=tmp_path)
    class Offline:
        def get_json(self, url): raise OSError('offline')
    prices, report = m.fetch_tablet_affix_prices(Offline(), 'http://test.invalid', LEAGUE, server='cn', cache_dir=tmp_path)
    assert prices and report['source'] == 'cache' and report['server'] == 'cn'
    assert len(list(tmp_path.glob('*.json'))) == 2


def test_cn_league_resolution_preserves_historical_selection():
    class Directory:
        def get_json(self, url):
            return dict(server='cn', stale=False, default=LEAGUE, source_season='0.5.5', data=[
                dict(name=LEAGUE, source_season='0.5.5', current=True, hardcore=False),
                dict(name='奥杜尔秘符', hardcore=False), dict(name='永久', hardcore=False)])
    assert m.resolve_cn_tablet_league(Directory(), 'http://test.invalid', '0.5.5') == LEAGUE
    assert m.resolve_cn_tablet_league(Directory(), 'http://test.invalid', 'RunesofAldur', False) == '奥杜尔秘符'
    assert m.resolve_cn_tablet_league(Directory(), 'http://test.invalid', 'standard', False) == '永久'
    with pytest.raises(ValueError):
        m.resolve_cn_tablet_league(Directory(), 'http://test.invalid', 'unknown', False)
