"""Whole-item market isolation, name routing and native currency regressions."""
import base64
from copy import deepcopy
import gzip
import json
from pathlib import Path
import struct
from urllib.parse import quote, parse_qs, urlparse
import zipfile

import pytest

from tests.test_tablet_affixes import synthetic_baseitems, refs, names
import build_poe2scout_price_patch as builder
import poe2_whole_tablets as m

LEAGUE = '周年庆巅峰挑战'
BASE = 'http://market.invalid'


def row(rarity='normal', **changes):
    unique = rarity == 'unique'
    result = dict(id='Freedom_of_Faith' if unique else 'Ritual_Tablet:' + rarity,
                  base_id='Ritual_Tablet', rarity=rarity, name='信念的自由' if unique else '祭祀石板',
                  name_en='Freedom of Faith' if unique else 'Ritual Tablet', base_name='祭祀石板',
                  status='priced', sample_count=10, prices={
                      'exalted': {'count': 8, 'min': 90, 'low_sample_median': 100, 'max': 110},
                      'divine': {'count': 2, 'min': .2, 'low_sample_median': .3, 'max': .4},
                  })
    query = dict(status={'option': 'securable'}, type=result['base_name'],
                 stats=[dict(type='and', filters=[dict(id='implicit.stat_3166002380', value={'min': 5 if unique else 10})])],
                 filters={'type_filters': {'filters': {'category': {'option': 'map.tablet'}, 'rarity': {'option': rarity}}},
                          'trade_filters': {'filters': {'collapse': {'option': 'false'}}}})
    if unique:
        query['name'] = result['name']
    result['trade_url'] = trade(query)
    result.update(changes)
    return result


def trade(query):
    token = base64.urlsafe_b64encode(gzip.compress(json.dumps(query).encode())).decode().rstrip('=')
    return f'https://poe.game.qq.com/trade2/search/poe2/{quote(LEAGUE)}/{token}'


def page(rows=None, **changes):
    rows = [row()] if rows is None else rows
    payload = dict(server='cn', market='whole-tablet', league=LEAGUE, stale=False,
                   updated_at='2026-09-26T11:00:00+00:00', snapshot={'id': 'snapshot-1'},
                   collection={'run_id': 'run-1'}, data=rows, offset=0, total=len(rows))
    payload.update(changes)
    return payload


class Client:
    def __init__(self, *pages): self.pages = pages; self.urls = []
    def get_json(self, url):
        self.urls.append(url)
        offset = int(parse_qs(urlparse(url).query)['offset'][0])
        return deepcopy(next((p for p in self.pages if p['offset'] == offset), self.pages[0]))


def fetch(client, **kwargs):
    return m.fetch_cn_whole_tablets(client, BASE, LEAGUE, **kwargs)


def test_prices_stay_in_original_units_and_prefer_normal_name_reference():
    payload = page([row(r) for r in ('normal', 'magic', 'rare', 'unique')])
    payload['data'][2]['prices'] = {'chaos': dict(count=10, min=1, low_sample_median=2, max=3)}
    client = Client(payload)
    report = fetch(client)
    reference = report['base_prices']['Ritual_Tablet']
    assert reference['price'] == '100E' and reference['variant'] == 'Normal'
    assert reference['selection'] == 'normal'
    assert reference['variants']['rare']['price'] == '2C'
    assert report['unique_prices']['freedom of faith']['price'] == '100E'
    assert report['unique_prices']['freedom of faith']['sample_count'] == 8
    assert len(client.urls) == 1 and '/whole-tablets/prices?' in client.urls[0]
    params = parse_qs(urlparse(client.urls[0]).query)
    assert params['league'] == [LEAGUE] and params['server'] == ['cn']
    assert report['reference_note'].startswith('整件低价挂牌样本参考')


def test_missing_normal_uses_available_reference_without_fabricating_quotes():
    report = fetch(Client(page([row('magic'), row('normal', status='no_listings', prices={}),
                               row('unique', status='pending', prices={})])))
    reference = report['base_prices']['Ritual_Tablet']
    assert reference['price'] == '100E' and reference['variant'] == 'Magic'
    assert set(reference['variants']) == {'magic'}
    assert report['unique_catalog'] == {'freedom of faith': 'Freedom_of_Faith'}
    assert not report['unique_prices'] and len(report['skipped']) == 2


@pytest.mark.parametrize('key,value', [('server', 'international'), ('market', 'tablet'),
    ('league', 'Forbidden Rites'), ('stale', None), ('offset', 99), ('total', 3000)])
def test_rejects_wrong_market_or_invalid_pagination(key, value):
    with pytest.raises(ValueError): fetch(Client(page(**{key: value})))


@pytest.mark.parametrize('reverse', [False, True])
def test_missing_normal_chooses_lowest_comparable_reference(reverse):
    rows = [row('magic'), row('rare', prices={
        'exalted': dict(count=10, min=10, low_sample_median=20, max=30)})]
    if reverse:
        rows.reverse()
    reference = fetch(Client(page(rows)))['base_prices']['Ritual_Tablet']
    assert reference['price'] == '20E' and reference['variant'] == 'Rare'
    assert reference['selection'] == 'lowest_available_native_currency'


def test_missing_normal_never_compares_unconverted_currency_numbers():
    rows = [row('magic'), row('rare', prices={
        'divine': dict(count=2, min=1, low_sample_median=1, max=1)})]
    reference = fetch(Client(page(rows)))['base_prices']['Ritual_Tablet']
    assert reference['price'] == '100E' and reference['variant'] == 'Magic'
    assert reference['variants']['rare']['price'] == '1D'


def test_no_valid_rarity_leaves_base_unpriced():
    report = fetch(Client(page([row(r, status='no_listings', prices={})
                               for r in m.RARITIES] + [row('unique')])))
    assert not report['base_prices'] and len(report['skipped']) == 3


@pytest.mark.parametrize('changed', [dict(snapshot={'id': 'snapshot-2'}), dict(updated_at='new'),
                                      dict(collection={'run_id': 'new'}), dict(total=4)])
def test_rejects_mixed_revisions_across_pages(changed):
    second = page([row('rare')], offset=1, total=2)
    second.update(changed)
    with pytest.raises(ValueError): fetch(Client(page(total=2), second))


def test_pagination_retries_entire_snapshot_without_duplicate_prices():
    class Changing:
        def __init__(self): self.calls = 0
        def get_json(self, url):
            self.calls += 1
            offset = int(parse_qs(urlparse(url).query)['offset'][0])
            return page([row('normal' if offset == 0 else 'rare')], offset=offset, total=2,
                        snapshot={'id': 'old' if self.calls == 1 else 'new'})
    client = Changing()
    result = fetch(client)
    assert client.calls == 4 and result['rows'] == 2 and result['pages'] == 2


def test_live_first_and_same_market_cache_fallback_even_when_stale(tmp_path):
    first = fetch(Client(page()), cache_dir=tmp_path)
    assert first['source'] == 'live'
    fresh = page([row(prices={'divine': dict(count=10, min=1, low_sample_median=2, max=3)})], stale=True)
    assert fetch(Client(fresh), cache_dir=tmp_path)['base_prices']['Ritual_Tablet']['price'] == '2D'
    class Offline:
        def get_json(self, url): raise OSError('offline')
    cached = fetch(Offline(), cache_dir=tmp_path)
    assert cached['source'] == 'cache' and cached['stale'] is True
    assert cached['base_prices']['Ritual_Tablet']['price'] == '2D'
    with pytest.raises(OSError): m.fetch_cn_whole_tablets(Offline(), BASE, '永久', cache_dir=tmp_path)
    with pytest.raises(OSError): m.fetch_cn_whole_tablets(Offline(), BASE + '/other', LEAGUE, cache_dir=tmp_path)


@pytest.mark.parametrize('mutation', ['uses', 'stat', 'name', 'type', 'corrupted', 'affix', 'host', 'league'])
def test_trade_scope_changes_skip_only_the_affected_item(mutation):
    bad = row('unique')
    token = bad['trade_url'].rsplit('/', 1)[-1]
    query = json.loads(gzip.decompress(base64.urlsafe_b64decode(token + '=' * (-len(token) % 4))))
    if mutation == 'uses': query['stats'][0]['filters'][0]['value']['min'] = 1
    if mutation == 'stat': query['stats'][0]['filters'][0]['id'] = 'implicit.stat_123'
    if mutation == 'name': query['name'] = '另一物品'
    if mutation == 'type': query['type'] = '其他底材'
    if mutation == 'corrupted': query['filters']['misc_filters'] = {'corrupted': True}
    if mutation == 'affix': query['stats'][0]['filters'].append({'id': 'explicit.stat_123'})
    bad['trade_url'] = trade(query)
    if mutation == 'host': bad['trade_url'] = bad['trade_url'].replace('poe.game.qq.com', 'www.pathofexile.com')
    if mutation == 'league': bad['trade_url'] = bad['trade_url'].replace(quote(LEAGUE), 'Standard')
    result = fetch(Client(page([row(), bad])))
    assert result['rows'] == 1 and not result['unique_prices']
    assert result['skipped'][0]['id'] == 'Freedom_of_Faith'


@pytest.mark.parametrize('value', [-1, 0, 'NaN', 'Infinity', 'bad', 1000])
def test_invalid_median_never_becomes_a_price(value):
    bad = row('unique'); bad['prices']['exalted']['low_sample_median'] = value
    assert not fetch(Client(page([row(), bad])))['unique_prices']


def test_missing_median_can_use_valid_minimum():
    r = row(); r['prices']['exalted'].pop('low_sample_median')
    result = fetch(Client(page([r])))
    assert result['quotes'][0]['price'] == '90E' and result['quotes'][0]['statistic'] == 'min'


def test_names_preserve_affix_inheritance_english_filters_and_other_resources(tmp_path):
    report = fetch(Client(page([row('normal'), row('rare')])))
    raw = synthetic_baseitems()
    import poe2_tablet_prices as affixes
    redirected, _ = affixes._redirect_tablet_base_items(raw, {'Ritual'})
    # Migrate the v1.0.5 multi-rarity label without touching the font translation.
    old_labeled, _ = affixes.price_tablet_names(redirected, {
        'Ritual_Tablet': {'price': '普90E 魔80E 稀2C'}})
    dat = tmp_path / 'base.datc64'; dat.write_bytes(old_labeled)
    z = tmp_path / 'patch.zip'
    target = 'data/balance/simplified chinese/baseitemtypes.datc64'
    with zipfile.ZipFile(z, 'w') as a:
        a.writestr(target, old_labeled)
        a.writestr(refs.ENGLISH_BASEITEMS, synthetic_baseitems(True))
        a.writestr('data/statdescriptions/poe2price/ritual_tablet_stat_descriptions.csd', b'unchanged')
    for _ in range(2):
        assert len(builder.apply_cn_whole_tablet_names(dat, z, target, report)) == 1
        assert names.scan_base_item_names(dat.read_bytes())[0].name == '[100E|祭祀碑牌]'
        # Name changes leave inheritance pointers intact, including our CSD route.
        assert dat.read_bytes()[44:52] == redirected[44:52]
    with zipfile.ZipFile(z) as a:
        assert a.read(refs.ENGLISH_BASEITEMS) == synthetic_baseitems(True)
        assert a.read(target) == dat.read_bytes()
        assert a.read('data/statdescriptions/poe2price/ritual_tablet_stat_descriptions.csd') == b'unchanged'
    before = z.read_bytes()
    assert builder.apply_cn_whole_tablet_names(dat, z, refs.ENGLISH_BASEITEMS, report) == []
    assert z.read_bytes() == before
    assert names.scan_base_item_names(refs.clean_tablet_layer(dat.read_bytes()))[0].name == '祭祀碑牌'


def words_fixture(path, display='字体补丁译名'):
    raw = bytearray(4 + builder.WORDS_ROW_SIZE); struct.pack_into('<I', raw, 0, 1)
    base = len(raw)
    for offset, value in [(builder.WORDS_EN_NAME_OFFSET, 'Freedom of Faith'),
                          (builder.WORDS_DISPLAY_NAME_OFFSET, display)]:
        struct.pack_into('<I', raw, 4 + offset, len(raw) - base)
        raw.extend((value + '\0\0').encode('utf-16-le'))
    path.write_bytes(raw)


def test_unique_names_match_english_identity_preserve_translation_and_cleanup_missing(tmp_path):
    source = tmp_path / 'words.datc64'; output = tmp_path / 'patched.datc64'
    words_fixture(source)
    unique_names = {'freedomoffaith': builder.UniqueName(0, 'Freedom of Faith', '字体补丁译名')}
    prices = fetch(Client(page([row('unique')])))['unique_prices']
    for _ in range(2):
        count, rows, missing, fallbacks = builder.patch_unique_word_prices_with_cn_fallback(
            source, unique_names, {}, {}, output, 'markup', prices)
        assert count == 1 and not missing and fallbacks == 0
        data = output.read_bytes()
        assert builder.read_words_row(data, builder.detect_words_layout(data), 0).display_name == '[100E|字体补丁译名]'
        assert rows[0]['price_exalted'] == '' and 'cn-whole-tablets' in rows[0]['source_pair']
        source.write_bytes(data)
    count, rows, missing, _ = builder.patch_unique_word_prices_with_cn_fallback(
        source, unique_names, {}, {}, output, 'markup', {'freedom of faith': None})
    assert count == 0 and missing and rows[0]['status'] == 'cleaned'
    data = output.read_bytes()
    assert builder.read_words_row(data, builder.detect_words_layout(data), 0).display_name == '字体补丁译名'
