from decimal import Decimal
import base64
import gzip
import json
from pathlib import Path
import struct
import subprocess
import sys
from urllib.parse import parse_qs, urlparse
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "物价补丁/tools"))
import poe2_tablet_prices as m
import poe2_name_price_patch as names
import poe2_tablet_refs as refs
from poe2_price_labels import format_unique_price_name, strip_existing_price

LEAGUE = "Forbidden Rites"


def selected(price, variant='Normal'):
    return {'price':price, 'variant':variant, 'selection':'normal' if variant=='Normal' else 'lowest_available'}


def synthetic_baseitems(english=False):
    metadata = ["Metadata/Items/TowerAugment/RitualAugment", "Metadata/Items/TowerAugment/BreachAugment", "Metadata/Items/Currency/CurrencyAddModToRare"]
    rows = bytearray(4 + len(metadata) * 360)
    struct.pack_into("<I", rows, 0, len(metadata))
    strings = bytearray(b'\xbb' * 8)

    def add(text):
        at = len(strings)
        strings.extend((text + "\0").encode("utf-16-le"))
        return at

    for i, text in enumerate(metadata):
        at = 4 + i * 360
        struct.pack_into("<Q", rows, at, add(text))
        display_names = ["Ritual Tablet", "Breach Tablet", "Exalted Orb"] if english else ["祭祀碑牌", "裂痕碑牌", "崇高石"]
        struct.pack_into("<Q", rows, at + 32, add(display_names[i]))
        struct.pack_into("<Q", rows, at + 40, add(refs.ORIGINAL))
    return bytes(rows + strings)


def quote(identifier="one", text="Map has (15-20)% increased Monster Rarity", price=500):
    return {"id": identifier, "tablet": "Ritual_Tablet", "text_en": text, "status": "ok", "sample_count": 10,
            "name_en":"Challenger's", "generation":"prefix",
            "converted": {"currency": "exalted", "low_sample_median": price, "missing_count": 0}}


def game_tables(tmp_path):
    def table(name, width, identifier, configure=None):
        fixed = bytearray(4 + width); struct.pack_into('<I', fixed, 0, 1)
        heap = bytearray(b'\xbb' * 8)
        def append(data):
            pointer = len(heap); heap.extend(data); return pointer
        struct.pack_into('<Q', fixed, 4, append((identifier+'\0').encode('utf-16-le')))
        if configure: configure(fixed, append)
        path = tmp_path/(name+'.datc64'); path.write_bytes(fixed+heap); return path
    def mod(fixed, append):
        struct.pack_into('<I',fixed,4+94,34)
        struct.pack_into('<Q',fixed,4+98,append("Challenger's\0".encode('utf-16-le')))
        struct.pack_into('<I',fixed,4+106,1)
        struct.pack_into('<QQ',fixed,4+158,1,append(struct.pack('<QQ',0,0)))
        struct.pack_into('<QQ',fixed,4+677,1,append(struct.pack('<i',1)))
    return dict(tablet_mods=table('mods',693,'test_mod',mod),
                tablet_stats=table('stats',106,'test_stat'),tablet_tags=table('tags',44,'default'))


def page(rows, offset=0, total=None, rarity='rare'):
    rows = [dict(row, trade_url=row.get('trade_url') or trade_url(row['id'], rarity)) for row in rows]
    return {"snapshot": {"id": "snapshot", "league": LEAGUE, "stale": False, "config": {"min_uses": 10, "rarity": rarity}},
            "exchange_rates": {"league": LEAGUE, "stale": False, "primary": "divine", "values": {"exalted": 0.002, "chaos": 0.1}},
            "offset": offset, "total": len(rows) if total is None else total, "data": rows}


def trade_url(identifier, rarity):
    query = {'filters': {'type_filters': {'filters': {'rarity': {'option': rarity}}}},
             'stats': [{'type': 'and', 'filters': [{'id': 'explicit.' + identifier}]}]}
    token = base64.urlsafe_b64encode(gzip.compress(json.dumps(query).encode())).decode().rstrip('=')
    return 'https://www.pathofexile.com/trade2/search/poe2/Forbidden%20Rites/' + token


class Client:
    def __init__(self, pages): self.pages = pages; self.urls = []
    def get_json(self, url):
        self.urls.append(url)
        return self.pages[int(parse_qs(urlparse(url).query)["offset"][0])]


def csd():
    return ('description\r\n\t1 test_stat\r\n\t2\r\n'
            '\t\t1|# "Map has {0}% increased Monster Rarity"\r\n'
            '\t\t#|-1 "Map has {0}% reduced Monster Rarity" negate 1\r\n'
            '\tlang "Traditional Chinese"\r\n\t2\r\n'
            '\t\t1|# "地圖增加{0}%[MonsterRarity|怪物稀有度]"\r\n'
            '\t\t#|-1 "地圖減少{0}%[MonsterRarity|怪物稀有度]" negate 1\r\n'
            '\tlang "Simplified Chinese"\r\n\t2\r\n'
            '\t\t1|# "地图增加{0}%[MonsterRarity|怪物稀有度]"\r\n'
            '\t\t#|-1 "地图减少{0}%[MonsterRarity|怪物稀有度]" negate 1\r\n')


def test_snapshot_pagination_preserves_distinct_numeric_tiers():
    client = Client({0: page([quote()], total=2), 1: page([quote("two", "Map has (21-30)% increased Monster Rarity", 1000)], offset=1, total=2)})
    prices, report = m.fetch_tablet_affix_prices(client, "http://example.invalid", LEAGUE)
    assert [(q.low, q.high, q.price) for q in prices["Ritual_Tablet"]] == [(15, 20, 500), (21, 30, 1000)]
    assert report["pages"] == 2 and len(client.urls) == 2


@pytest.mark.parametrize("field,value", [("league", "Standard"), ("stale", True), ("id", "changed")])
def test_bad_second_page_never_yields_partial_prices(field, value):
    second = page([quote("two")], offset=1, total=2)
    second["snapshot"][field] = value
    with pytest.raises(ValueError):
        m.fetch_tablet_affix_prices(Client({0: page([quote()], total=2), 1: second}), "http://example.invalid", LEAGUE)


def test_old_magic_snapshot_retains_prices_and_sampling_dates():
    payload = page([quote()], rarity='magic')
    payload['snapshot'].update(stale=True, published_at='2026-09-22T07:09:35+00:00',
                               oldest_sample_at='2026-09-22T06:17:39+00:00')
    prices, report = m.fetch_tablet_affix_prices(Client({0: payload}), 'http://example.invalid',
        LEAGUE, rarity='magic', allow_stale_snapshot=True)
    assert prices['Ritual_Tablet'][0].price == 500
    assert report['snapshot_stale'] is True and report['allow_stale_snapshot'] is True
    assert report['allow_stale'] is False and report['exchange_rates_stale'] is False
    assert report['published_at'] == payload['snapshot']['published_at']
    assert report['oldest_sample_at'] == payload['snapshot']['oldest_sample_at']


@pytest.mark.parametrize('section,field,value', [
    ('snapshot', 'league', 'Standard'), ('exchange_rates', 'league', 'Standard'),
    ('snapshot', 'stale', None), ('exchange_rates', 'stale', True),
    ('exchange_rates', 'stale', None), ('snapshot', 'id', 'changed'),
])
def test_old_snapshot_permission_keeps_market_currency_and_pagination_checks(section, field, value):
    first = page([quote()], total=2, rarity='magic')
    second = page([quote('two')], offset=1, total=2, rarity='magic')
    first['snapshot']['stale'] = second['snapshot']['stale'] = True
    if value is None:
        second[section].pop(field)
    else:
        second[section][field] = value
    with pytest.raises(ValueError):
        m.fetch_tablet_affix_prices(Client({0: first, 1: second}), 'http://example.invalid',
            LEAGUE, rarity='magic', allow_stale_snapshot=True)


def test_snapshot_retry_restarts_all_pages_without_mixing_prices(monkeypatch):
    import time
    waits = []; notices = []
    monkeypatch.setattr(time, 'sleep', waits.append)
    old = page([quote(price=500)], total=2)
    new_first = page([quote(price=750)], total=2)
    new_last = page([quote('two', price=1000)], offset=1, total=2)
    new_first['snapshot']['id'] = new_last['snapshot']['id'] = 'new-snapshot'
    class ChangingClient:
        def __init__(self): self.responses = iter([old, new_last, new_first, new_last]); self.offsets = []
        def get_json(self, url):
            self.offsets.append(int(parse_qs(urlparse(url).query)['offset'][0]))
            return next(self.responses)
    client = ChangingClient()
    prices, report = m.fetch_tablet_affix_prices(client, 'http://example.invalid', LEAGUE,
        snapshot_retries=2, on_retry=notices.append)
    assert client.offsets == [0, 1, 0, 1]
    assert [q.price for q in prices['Ritual_Tablet']] == [750, 1000]
    assert report['snapshot_attempts'] == 2 and len(report['snapshot_retry_reasons']) == 1
    assert waits == [1] and len(notices) == 1


def test_snapshot_retry_is_bounded_and_does_not_relax_currency_validation(monkeypatch):
    import time
    waits = []; monkeypatch.setattr(time, 'sleep', waits.append)
    payload = page([quote()], rarity='magic')
    payload['snapshot']['stale'] = True; payload['exchange_rates']['stale'] = True
    client = Client({0: payload})
    with pytest.raises(m.TabletSnapshotError) as error:
        m.fetch_tablet_affix_prices(client, 'http://example.invalid', LEAGUE, rarity='magic',
            allow_stale_snapshot=True, snapshot_retries=2)
    assert len(client.urls) == 3 and waits == [1, 2]
    assert error.value.snapshot_attempts == 3
    assert len(error.value.snapshot_retry_reasons) == 3


def test_wrong_league_is_rejected_without_snapshot_retry():
    payload = page([quote()]); payload['snapshot']['league'] = 'Standard'
    client = Client({0: payload})
    with pytest.raises(ValueError, match='league'):
        m.fetch_tablet_affix_prices(client, 'http://example.invalid', LEAGUE, snapshot_retries=2)
    assert len(client.urls) == 1


def test_bad_status_and_partial_currency_conversion_are_not_quotes():
    bad = quote(); bad["status"] = "error"
    partial = quote("partial"); partial["converted"]["missing_count"] = 1
    prices, _ = m.fetch_tablet_affix_prices(Client({0:page([bad, partial])}), "http://example.invalid", LEAGUE)
    assert prices == {}


@pytest.mark.parametrize("unit,amount,expected", [("divine", 5, "2500"), ("chaos", 5, "250"), ("exalted", 5, "5")])
def test_raw_currency_conversion(unit, amount, expected):
    assert m._tablet_price_from_row({"prices":{unit:{"low_sample_median":amount,"min":1}}}, {"divine":Decimal(1), "exalted":Decimal("0.002"), "chaos":Decimal("0.1")}) == Decimal(expected)


def test_link_text_and_plural_forms_match_market_text():
    assert m._tablet_text_key("{0}% increased [Rarity] of Items found in Map") == m._tablet_text_key("(8-12)% increased Rarity of Items found in Map")
    assert m._tablet_text_key("Map is inhabited by {0} additional Rogue Exile") == m._tablet_text_key("Map is inhabited by 1 additional Rogue Exiles")


@pytest.mark.parametrize('singular,plural', [
    ('Map contains an additional [Strongbox]', 'Map contains 1 additional Strongboxes'),
    ('Ritual Altars in Map allow rerolling Favours an additional time', 'Ritual Altars in Map allow rerolling Favours (1-3) additional times'),
    ('The first unearthed Runic Monster will be a Rare Monster in Map', 'The first (1-2) unearthed Runic Monsters will be Rare Monsters in Map'),
    ('Expeditions contain an Additional Verisium Sentry in Map', 'Expeditions contain (1-2) Additional Verisium Sentries in Map'),
])
def test_singular_first_matching_branches_match_their_market_range(singular, plural):
    assert m._tablet_text_key(singular) == m._tablet_text_key(plural)


def test_singular_and_plural_branches_are_both_priced_with_missing_locale(tmp_path):
    source = tmp_path/'strongbox.csd'
    source.write_text('description\n\t1 strongbox\n\t2\n\t\t1 "Map contains an additional [Strongbox]"\n'
                      '\t\t2|# "Map contains {0} additional [Strongbox|Strongboxes]" canonical_line\n'
                      '\tlang "Traditional Chinese"\n\t2\n\t\t1 "地圖內含有額外的一個保險箱"\n'
                      '\t\t2|# "地圖內含有額外的{0}個保險箱" canonical_line\n',encoding='utf-8')
    result,matched,changed=m._append_tablet_price_to_csd(source,[m.Quote('Map contains (1-2) additional Strongboxes',Decimal(500),1,2)],Decimal(500))
    text=result.decode()
    assert matched==1 and changed==4
    for language in ['Traditional Chinese','Simplified Chinese']:
        section=text.split(f'lang "{language}"')[1].split('lang "')[0]
        for value in [1,2]:
            for line in section.splitlines(keepends=True):
                record=m.LINE.match(line)
                if not record:continue
                lo,hi=m.condition_bounds(record[2])
                if (lo is None or value>=lo) and (hi is None or value<=hi):
                    assert record[3].endswith('=1.00D')
                    break
            else: pytest.fail('no matching price branch')
    m.validate_csd(text)


@pytest.mark.parametrize("encoding,bom", [("utf-16-le", b"\xff\xfe"), ("utf-8", b"")])
def test_csd_preserves_syntax_encoding_english_and_unpriced_branches(tmp_path, encoding, bom):
    source = tmp_path / "tablet.csd"; source.write_bytes(bom + csd().encode(encoding))
    result, matched, changed = m._append_tablet_price_to_csd(source, [m.Quote("Map has (15-20)% increased Monster Rarity", Decimal(500), 15, 20)], Decimal(500))
    assert result.startswith(bom)
    text = result[len(bom):].decode(encoding)
    assert '\x01' not in text
    assert '15|20 "地圖增加{0}%[MonsterRarity|怪物稀有度]=1.00D"\r\n' in text
    assert '1|# "地圖增加{0}%[MonsterRarity|怪物稀有度]"\r\n' in text
    assert '#|-1 "地圖減少{0}%[MonsterRarity|怪物稀有度]" negate 1\r\n' in text
    assert text.split('lang "')[0] == csd().split('lang "')[0]
    assert matched == 1 and changed == 2
    m.validate_csd(text)


def test_reduced_branch_and_hundredth_units_are_respected(tmp_path):
    source = tmp_path / "tablet.csd"
    source.write_bytes(csd().replace(' negate 1', ' negate 1 divide_by_one_hundred 1').encode('utf-8'))
    result, _, changed = m._append_tablet_price_to_csd(source, [m.Quote("Map has (15-20)% reduced Monster Rarity", Decimal(500), 15, 20)], Decimal(500))
    text = result.decode('utf-8')
    assert '-2000|-1500 "地圖減少{0}%[MonsterRarity|怪物稀有度]=1.00D" negate 1 divide_by_one_hundred 1' in text
    assert '地圖增加{0}%[MonsterRarity|怪物稀有度]=1.00D' not in text
    assert changed == 2


def test_known_tablet_redirects_are_compatible_but_other_fields_are_not():
    original = synthetic_baseitems()
    redirected, count = m._redirect_tablet_base_items(original, {"Ritual", "Breach"})
    assert count == 2
    assert names.build_structure_signature(redirected) == names.build_structure_signature(original)
    altered = bytearray(redirected); altered[4 + 80] ^= 1
    assert names.build_structure_signature(altered) != names.build_structure_signature(original)
    wrong = redirected.replace('Poe2Price/Ritual'.encode('utf-16-le'), 'Poe2Price/Breach'.encode('utf-16-le'))
    assert names.build_structure_signature(wrong) != names.build_structure_signature(original)
    cleaned = refs.clean_references(redirected)
    assert names.build_structure_signature(cleaned) == names.build_structure_signature(original)
    layout = names.detect_base_item_layout(cleaned)
    for row in range(2):
        pointer = struct.unpack_from('<Q', cleaned, 4 + row * 360 + 40)[0]
        assert names.read_string_offset(cleaned, layout, pointer)[0] == refs.ORIGINAL


def test_ninja_keeps_rarity_prices_separate():
    class Ninja:
        def get_json(self, url):
            return {"core":{"primary":"divine", "rates":{"exalted":500}}, "lines":[
                {"baseType":"Ritual Tablet", "variant":variant, "primaryValue":price, "listingCount":10, "corrupted":False}
                for variant,price in [("Normal", 1), ("Magic", 2), ("Rare", 3)]
            ]}
    result = m.fetch_poe_ninja_precursor_tablets(Ninja(), LEAGUE)
    assert result["prices"]["Ritual_Tablet"] == {"Normal":"1.00D", "Magic":"2.00D", "Rare":"3.00D"}
    assert result['base_prices']['Ritual_Tablet'] == selected('1.00D')


def test_tablets_and_uniques_share_the_same_formatter_and_cleaner():
    import build_poe2scout_price_patch as builder
    assert m.format_unique_price_name is builder.format_unique_price_name
    assert m.strip_existing_price is builder.strip_existing_price


def test_overseer_without_normal_uses_lowest_available_valid_variant():
    class Ninja:
        def get_json(self, url):
            return {'core':{'primary':'divine','rates':{'exalted':500}},'lines':[
                {'baseType':'Overseer Tablet','variant':variant,'primaryValue':price,'listingCount':count,'corrupted':corrupted}
                for variant,price,count,corrupted in [('Magic',0.3285,8150,False),('Rare',0.1189,10000,False),
                    ('Normal',0.01,0,False),('Normal',0.01,10,True)]]}
    assert m.fetch_poe_ninja_precursor_tablets(Ninja(),LEAGUE)['base_prices']['Overseer_Tablet'] == selected('0.12D','Rare')


def test_constant_cap_quote_is_retained_and_priced_against_game_variable(tmp_path):
    text = 'Abyssal Monsters have (8-12)% increased Effectiveness for each closed Pit, up to 100%'
    quotes, report = m.fetch_tablet_affix_prices(Client({0:page([quote(text=text)])}), 'http://unused', LEAGUE)
    assert report['total'] == report['rows'] == 1
    assert (quotes['Ritual_Tablet'][0].low,quotes['Ritual_Tablet'][0].high)==(8,12)
    source=tmp_path/'abyss.csd'
    source.write_text('description\n\t1 map_abyss_monster_potency_+%_per_chasm_closed\n\t1\n'
        '\t\t1|# "[ContainsAbyss|Abyssal] Monsters have {0}% increased [MonsterEffectiveness|Effectiveness] for each closed Pit, up to 100%"\n'
        '\tlang "Traditional Chinese"\n\t1\n'
        '\t\t1|# "每有一個已關閉的坑洞，增加{0}%[ContainsAbyss|深淵]怪物[MonsterEffectiveness|效用]，最多100%"\n',encoding='utf-8')
    output,matched,changed=m._append_tablet_price_to_csd(source,quotes['Ritual_Tablet'],Decimal(500))
    assert matched==1 and changed==2
    assert '8|12 "每有一個已關閉的坑洞，增加{0}%[ContainsAbyss|深淵]怪物[MonsterEffectiveness|效用]，最多100%=1.00D"' in output.decode()
    bad=[m.Quote(text.replace('100%','200%'),Decimal(500),8,12)]
    _,matched,changed=m._append_tablet_price_to_csd(source,bad,Decimal(500))
    assert matched==changed==0


def test_constant_before_variable_is_not_used_as_price_range():
    q=m.Quote('After 10 seconds, grants (8-12)% Effectiveness',Decimal(500))
    resolved=m.quote_for_record(q,'After 10 seconds, grants {0}% Effectiveness')
    assert (resolved.low,resolved.high)==(8,12)
    assert m.quote_for_record(q,'After 20 seconds, grants {0}% Effectiveness') is None
    assert m.quote_for_record(q,'After {0} seconds, grants {1}% Effectiveness') is None


@pytest.mark.parametrize('style', ['AT1', 'AT2', 'AT3', 'DF1', 'DF2', 'DF3'])
def test_localization_styles_preserve_numeric_identity(style):
    q = m.Quote('After 10 seconds, grants (8-12)% Effectiveness', Decimal(500))
    styled = f'<{style}>{{{{After 10 seconds, grants {{0}}% <other>{{{{Effectiveness}}}}}}}}'
    resolved = m.quote_for_record(q, styled)
    assert resolved is not None and (resolved.low, resolved.high) == (8, 12)
    assert m.quote_for_record(q, styled.replace('10 seconds', '20 seconds')) is None
    assert m.quote_for_record(q, styled[:-1]) is None
    assert m._tablet_display_text(f'<{style}>{{{{Value {{0}}}}}}') == 'Value {0}'


def test_shss_split_tiers_keep_styles_and_first_matching_price():
    # SHSS uses a singular branch, coloured tiers, and a final catch-all.
    english = ['an additional [Rarity|Rare] Monster', '{0} additional [Rarity|Rare] Monsters']
    records = []
    for language in [None, 'Traditional Chinese']:
        section = '' if language is None else f'\tlang "{language}"\r\n'
        section += '\t4\r\n'
        for index, (condition, style) in enumerate([('1','AT3'), ('2','AT2'), ('3','AT1'), ('#','AT1')]):
            body = ('Unstable [ContainsBreach|Breaches] in Map spawn ' + english[min(index,1)] + ' when Stabilised'
                    if language is None else '地圖內的不穩定[ContainsBreach|裂痕]會在穩定後生成{0}名額外[Rarity|稀有]怪物')
            section += f'\t\t{condition} "<{style}>{{{{{body}}}}}"\r\n'
        records.append(section)
    block = 'description\r\n\t1 map_unstable_breach_enrage_x_additional_rare_monsters\r\n' + ''.join(records)
    q = m.Quote('Unstable Breaches in Map spawn (1-2) additional Rare Monsters when Stabilised',
                Decimal(500), 1, 2, identifier='shss-breach', stat='map_unstable_breach_enrage_x_additional_rare_monsters')
    result, used, changed = m.price_block(block, [q], Decimal(500))
    assert used == {'shss-breach'} and changed > 0
    assert result.split('lang "')[0] == block.split('lang "')[0]
    for language in ['Traditional Chinese', 'Simplified Chinese']:
        section = result.split(f'lang "{language}"')[1].split('lang "')[0]
        parsed = [m.LINE.match(line) for line in section.splitlines(keepends=True) if m.LINE.match(line)]
        for value in [0, 1, 2, 3, 4]:
            first = next(r for r in parsed if
                (m.condition_bounds(r[2])[0] is None or value >= m.condition_bounds(r[2])[0]) and
                (m.condition_bounds(r[2])[1] is None or value <= m.condition_bounds(r[2])[1]))
            assert first[3].endswith('=1.00D') == (value in [1,2])
            assert first[3].startswith('<' + {1:'AT3',2:'AT2'}.get(value,'AT1') + '>{{')
    m.validate_csd(result)


def test_shss_styled_reduced_branch_preserves_negation_and_original_text():
    block = csd().replace('"Map has {0}% reduced Monster Rarity"',
                          '"<AT1>{{Map has {0}% reduced Monster Rarity}}"')
    block = block.replace('"地圖減少{0}%[MonsterRarity|怪物稀有度]"',
                          '"<AT1>{{地圖減少{0}%[MonsterRarity|怪物稀有度]}}"')
    result, used, _ = m.price_block(block,
        [m.Quote('Map has (20-30)% reduced Monster Rarity', Decimal(500),20,30,identifier='reduced')], Decimal(500))
    assert used == {'reduced'}
    assert '-30|-20 "<AT1>{{地圖減少{0}%[MonsterRarity|怪物稀有度]}}=1.00D" negate 1' in result
    assert '1|# "地圖增加{0}%[MonsterRarity|怪物稀有度]"' in result
    m.validate_csd(result)


def test_overlapping_conflicting_quotes_never_silently_choose_the_minimum():
    first=m.Quote('Map has (15-20)% increased Monster Rarity',Decimal(500),15,20)
    second=m.Quote('Map has 15% increased Monster Rarity',Decimal(1000),15,15)
    with pytest.raises(ValueError,match='ambiguous tablet prices'):
        m.price_block(csd(),[first,second],Decimal(500))


def test_legacy_name_suffix_migrates_and_markup_only_patch_is_detected(tmp_path):
    import csv
    original=synthetic_baseitems()
    rows,_=names.build_replacements(names.scan_base_item_names(original),
        [{'metadata_path':'Metadata/Items/TowerAugment/RitualAugment','new_name':'祭祀碑牌=0.38D'}], '=',False,'append',False)
    legacy=names.apply_replacements_append(original,rows)
    updated,_=m.price_tablet_names(legacy,{'Ritual_Tablet':selected('0.40D')})
    assert names.scan_base_item_names(updated)[0].name=='[0.40D|祭祀碑牌]'
    source=tmp_path/'source.dat';source.write_bytes(updated)
    exported=tmp_path/'names.csv';names.export_names(source,exported)
    with exported.open(encoding='utf-8-sig') as stream: records=list(csv.DictReader(stream))
    assert records[0]['tablet_reference_patched']=='True'
    assert records[1]['tablet_reference_patched']=='False'


def test_missing_game_mapping_cannot_mutate_patch_even_when_ninja_fails(tmp_path):
    source = tmp_path / "base.dat"; source.write_bytes(synthetic_baseitems())
    patched = tmp_path / "patched.dat"; patched.write_bytes(source.read_bytes())
    template = tmp_path / "template.it"; template.write_text('Mods\n{\nstat_description_list = "Data/StatDescriptions/tablet_stat_descriptions.csd"\n}\n', encoding='utf-8')
    descriptions = tmp_path / "tablet.csd"; descriptions.write_bytes(csd().encode('utf-8'))
    archive = tmp_path / "patch.zip"
    with zipfile.ZipFile(archive, 'w') as z: z.writestr('data/balance/traditional chinese/baseitemtypes.datc64', source.read_bytes())
    class Partial:
        def get_json(self, url):
            if 'poe.ninja' in url: raise TimeoutError('offline')
            return page([quote()], rarity=parse_qs(urlparse(url).query)['rarity'][0])
    args = dict(client=Partial(),api_base='http://example.invalid',league=LEAGUE,template_it=template,template_csd=descriptions,source_baseitems=source,patched_baseitems=patched,output_zip=archive,game_path='data/balance/traditional chinese/baseitemtypes.datc64',resource_report=tmp_path/'report.json')
    before = archive.read_bytes(); before_dat = patched.read_bytes()
    with pytest.raises(ValueError, match='Mods/Stats/Tags'):
        m.build_tablet_affix_resources(**args)
    assert archive.read_bytes() == before and patched.read_bytes() == before_dat


def test_cache_cleanup_removes_resources_and_clears_references(tmp_path):
    original = synthetic_baseitems(); redirected, _ = m._redirect_tablet_base_items(original, {'Ritual'})
    path = tmp_path/'cache.zip'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('data/balance/traditional chinese/baseitemtypes.datc64',redirected)
        z.writestr('metadata/items/toweraugments/poe2price/ritual.it',b'old')
    refs.clean_zip(path)
    with zipfile.ZipFile(path) as z:
        assert len(z.namelist()) == 1
        assert z.read(z.namelist()[0])[:1084] == original[:1084]


@pytest.mark.parametrize('runtime', ['isolated', 'embedded'])
def test_tablet_cli_validates_and_cleans_with_isolated_python(tmp_path, runtime):
    python = ROOT / 'desktop/.runtime/tools/python/poe_python.exe'
    if runtime == 'embedded' and not python.exists():
        pytest.skip('prepare the bundled Python runtime first')
    command = [sys.executable, '-I'] if runtime == 'isolated' else [str(python)]
    command.append(str(ROOT / '物价补丁/tools/poe2_tablet_refs.py'))
    original = synthetic_baseitems()
    redirected, _ = m._redirect_tablet_base_items(original, {'Ritual'})
    base_path = 'data/balance/traditional chinese/baseitemtypes.datc64'
    it_path = 'metadata/items/toweraugments/poe2price/ritual.it'
    csd_path = 'data/statdescriptions/poe2price/ritual_tablet_stat_descriptions.csd'
    archive = tmp_path / '碑牌补丁.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(base_path, redirected)
        z.writestr(it_path, f'Mods\n{{\nstat_description_list = "{csd_path}"\n}}\n')
        z.writestr(csd_path, csd())
        z.writestr('data/balance/words.datc64', b'preserved words')

    def run(*args):
        return subprocess.run(command + [str(archive), *args], cwd=tmp_path,
                              capture_output=True, timeout=30)

    validated = run('--validate')
    assert validated.returncode == 0, validated.stderr
    english = tmp_path / '英文底材.datc64'
    english.write_bytes(redirected)
    cleaned = run('--english', str(english))
    assert cleaned.returncode == 0, cleaned.stderr
    with zipfile.ZipFile(archive) as z:
        assert not any('/poe2price/' in name for name in z.namelist())
        for entry in (base_path, 'data/balance/baseitemtypes.datc64'):
            assert z.read(entry) == refs.clean_tablet_layer(redirected)
        assert z.read('data/balance/words.datc64') == b'preserved words'
    assert run('--validate').returncode == 0
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(base_path, redirected)
    invalid = run('--validate')
    assert invalid.returncode != 0
    assert b'missing referenced template' in invalid.stderr


def test_disabled_core_build_clears_old_test_inheritance_and_detects_it(tmp_path):
    import csv
    original = synthetic_baseitems()
    redirected, _ = m._redirect_tablet_base_items(original, {'Ritual'})
    redirected = redirected.replace('Poe2Price/Ritual'.encode('utf-16-le'), 'PriceTest20260920/Ritual'.encode('utf-16-le'))
    source = tmp_path/'source.dat'; source.write_bytes(redirected)
    exported = tmp_path/'names.csv'; names.export_names(source, exported)
    with exported.open(encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]['tablet_reference_patched'] == 'True'
    assert rows[1]['tablet_reference_patched'] == 'False'
    prices = tmp_path/'prices.csv'; prices.write_text('metadata_path,name,price\n', encoding='utf-8')
    archive = tmp_path/'clean.zip'; patched = tmp_path/'clean.dat'
    names.build_patch(source, prices, archive, patched, 'data/balance/baseitemtypes.datc64', '=', False, 'append', False, None)
    assert patched.read_bytes() == refs.clean_references(redirected)
    assert patched.read_bytes()[:1084] == original[:1084]


@pytest.mark.parametrize('templates_available', [False, True])
@pytest.mark.parametrize('legacy_english', [False, True])
def test_ninja_only_and_both_sources_offline_leave_valid_core(tmp_path, templates_available, legacy_english):
    source = tmp_path/'base.dat'; source.write_bytes(synthetic_baseitems())
    patched = tmp_path/'patched.dat'; patched.write_bytes(source.read_bytes())
    template = tmp_path/'template.it'
    template.write_text('Mods\n{\nstat_description_list = "Data/StatDescriptions/tablet_stat_descriptions.csd"\nenable_rarity = "magic"\nenable_rarity = "rare"\n}\n', encoding='utf-8')
    descriptions = tmp_path/'tablet.csd'; descriptions.write_bytes(csd().encode())
    if not templates_available:
        template.unlink(); descriptions.unlink()
    english = tmp_path/'english.dat'
    english_data = synthetic_baseitems(english=True)
    if legacy_english:
        english_data, _ = m.price_tablet_names(english_data, {'Ritual_Tablet':selected('0.24D')})
    english.write_bytes(english_data)
    supplement = tmp_path/'stats.csd'
    supplement.write_text('description\n\t1 tower_ritual_use_count\n\t1\n\t\t# "{0} uses remaining"\n\tlang "Traditional Chinese"\n\t1\n\t\t# "剩餘 {0} 次使用次數"\n', encoding='utf-8')
    archive = tmp_path/'core.zip'
    core_path = 'data/balance/traditional chinese/baseitemtypes.datc64'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(core_path, source.read_bytes())
        z.writestr('data/balance/traditional chinese/words.datc64', b'unchanged other layer')
    class NinjaOnly:
        def get_json(self, url):
            if 'poe.ninja' not in url: raise TimeoutError('API offline')
            return {'core':{'primary':'divine', 'rates':{'exalted':500}}, 'lines':[
                {'baseType':'Ritual Tablet', 'variant':variant, 'primaryValue':price, 'listingCount':10, 'corrupted':False}
                for variant, price in [('Normal', 1), ('Rare', 3)]]}
    args = dict(client=NinjaOnly(),api_base='http://example.invalid',league=LEAGUE,template_it=template,template_csd=descriptions,template_global_csd=supplement,source_baseitems=source,patched_baseitems=patched,output_zip=archive,game_path=core_path,resource_report=tmp_path/'report.json',english_baseitems=english)
    report = m.build_tablet_affix_resources(**args)
    assert report['status'] == 'partial' and report['api']['status'] == 'unavailable'
    with zipfile.ZipFile(archive) as z:
        entries = {p:z.read(p) for p in z.namelist()}
    refs.validate_resources(entries)
    assert entries['data/balance/traditional chinese/words.datc64'] == b'unchanged other layer'
    assert len(entries) == 3 and not any('/poe2price/' in path for path in entries)
    assert report['redirected_items'] == 0
    assert report['base_names'] == [{'tablet':'Ritual_Tablet', **selected('1.00D')}]
    assert names.scan_base_item_names(entries[core_path])[0].name == format_unique_price_name('祭祀碑牌','1.00D','markup')
    assert [e.name for e in names.scan_base_item_names(entries[refs.ENGLISH_BASEITEMS])] == [
        'Ritual Tablet', 'Breach Tablet', 'Exalted Orb']
    class Offline:
        def get_json(self, url): raise TimeoutError('offline')
    args['client'] = Offline()
    before = archive.read_bytes(); before_dat = patched.read_bytes()
    with pytest.raises(ValueError, match='sources unavailable'):
        m.build_tablet_affix_resources(**args)
    assert archive.read_bytes() == before and patched.read_bytes() == before_dat


def test_names_use_unique_markup_exact_base_paths_update_and_clean():
    original = synthetic_baseitems()
    unrelated, _ = names.build_replacements(names.scan_base_item_names(original),
        [{'metadata_path':'Metadata/Items/Currency/CurrencyAddModToRare','new_name':'崇高石=2D'}], '=', False, 'append', False)
    original = names.apply_replacements_append(original, unrelated)
    priced, rows = m.price_tablet_names(original, {'Ritual_Tablet':selected('0.38D'),
                                                'Breach_Tablet':selected('5.00D','Rare')})
    assert [e.name for e in names.scan_base_item_names(priced)] == ['[0.38D|祭祀碑牌]', '[5.00D|裂痕碑牌]', '崇高石=2D']
    assert len(rows) == 2
    updated, _ = m.price_tablet_names(priced, {'Ritual_Tablet':selected('0.40D')})
    assert names.scan_base_item_names(updated)[0].name == '[0.40D|祭祀碑牌]'
    assert m.price_tablet_names(updated, {'Ritual_Tablet':selected('0.40D')})[0] == updated
    cleaned = refs.clean_tablet_layer(updated)
    assert [e.name for e in names.scan_base_item_names(cleaned)] == ['祭祀碑牌', '裂痕碑牌', '崇高石=2D']
    assert refs.clean_tablet_layer(cleaned) == cleaned
    assert names.build_structure_signature(priced) == names.build_structure_signature(original)


@pytest.mark.parametrize('legacy_name', ['[0.37D|Breach Tablet]', 'Breach Tablet=0.37D'])
def test_filter_validator_rejects_legacy_english_labels_and_repair_keeps_affixes(legacy_name):
    original = synthetic_baseitems(english=True)
    replacements, _ = names.build_replacements(names.scan_base_item_names(original), [
        {'metadata_path':'Metadata/Items/TowerAugment/BreachAugment', 'new_name':legacy_name}
    ], '=', False, 'append', False)
    labelled = names.apply_replacements_append(original, replacements)
    redirected, _ = m._redirect_tablet_base_items(labelled, {'Breach'})
    entries = {
        refs.ENGLISH_BASEITEMS: redirected,
        'metadata/items/toweraugments/poe2price/breach.it':
            b'Mods\n{\nstat_description_list = "test.csd"\n}\n',
        'test.csd': csd().encode(),
    }
    with pytest.raises(ValueError, match='English BaseType.*item filters'):
        refs.validate_resources(entries)
    cleaned = refs.clean_tablet_names(redirected)
    entries[refs.ENGLISH_BASEITEMS] = cleaned
    refs.validate_resources(entries)
    assert [e.name for e in names.scan_base_item_names(cleaned)] == [
        'Ritual Tablet', 'Breach Tablet', 'Exalted Orb']
    layout = names.detect_base_item_layout(cleaned)
    for row in range(layout.row_count):
        at = 4 + row * layout.row_size + 40
        assert cleaned[at:at+8] == redirected[at:at+8]
    assert refs.clean_tablet_names(cleaned) == cleaned


def test_filter_validator_also_rejects_prices_on_non_tablet_english_bases():
    original = synthetic_baseitems(english=True)
    replacements, _ = names.build_replacements(names.scan_base_item_names(original), [
        {'metadata_path':'Metadata/Items/Currency/CurrencyAddModToRare', 'new_name':'Exalted Orb=2D'}
    ], '=', False, 'append', False)
    with pytest.raises(ValueError, match='English BaseType.*Exalted Orb'):
        refs.validate_resources({refs.ENGLISH_BASEITEMS:names.apply_replacements_append(original, replacements)})


def test_api_available_without_templates_still_updates_ninja_names(tmp_path):
    source = tmp_path/'source.dat'; source.write_bytes(synthetic_baseitems())
    patched = tmp_path/'patched.dat'; patched.write_bytes(source.read_bytes())
    archive = tmp_path/'patch.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('data/balance/traditional chinese/baseitemtypes.datc64', source.read_bytes())
        z.writestr('metadata/items/toweraugments/poe2price/ritual.it', b'old')
    class Both:
        def get_json(self, url):
            if 'poe.ninja' not in url:
                return page([quote()], rarity=parse_qs(urlparse(url).query)['rarity'][0])
            return {'core':{'primary':'divine','rates':{'exalted':500}},'lines':[
                {'baseType':'Ritual Tablet','variant':'Normal','primaryValue':1,'listingCount':10,'corrupted':False}]}
    report = m.build_tablet_affix_resources(client=Both(),api_base='http://unused',league=LEAGUE,
        template_it=None,template_csd=None,source_baseitems=source,patched_baseitems=patched,
        output_zip=archive,game_path='data/balance/traditional chinese/baseitemtypes.datc64',resource_report=tmp_path/'report.json')
    assert report['status'] == 'partial' and report['affix_templates']['status'] == 'unavailable'
    assert report['api']['status'] == report['poe_ninja_precursor_tablets']['status'] == 'ok'
    with zipfile.ZipFile(archive) as z:
        assert z.namelist() == ['data/balance/traditional chinese/baseitemtypes.datc64']
        assert names.scan_base_item_names(z.read(z.namelist()[0]))[0].name == '[1.00D|祭祀碑牌]'


def test_restore_and_disabled_build_remove_tablet_name_prices_in_both_languages(tmp_path):
    priced, _ = m.price_tablet_names(synthetic_baseitems(), {'Ritual_Tablet':selected('0.38D')})
    redirected, _ = m._redirect_tablet_base_items(priced, {'Ritual'})
    source = tmp_path/'source.dat'; source.write_bytes(redirected)
    english = tmp_path/'english.dat'; english.write_bytes(redirected)
    archive = tmp_path/'cache.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('data/balance/traditional chinese/baseitemtypes.datc64', redirected)
        z.writestr('metadata/items/toweraugments/poe2price/ritual.it', b'old')
    refs.clean_zip(archive, english)
    with zipfile.ZipFile(archive) as z:
        assert len(z.namelist()) == 2
        for path in z.namelist():
            clean = z.read(path)
            assert names.scan_base_item_names(clean)[0].name == '祭祀碑牌'
            assert refs.clean_tablet_layer(clean) == clean
    prices = tmp_path/'prices.csv'; prices.write_text('metadata_path,name,price\n', encoding='utf-8')
    patched = tmp_path/'clean.dat'
    names.build_patch(source, prices, archive, patched, 'data/balance/baseitemtypes.datc64', '=', False, 'append', False, None, True)
    assert names.scan_base_item_names(patched.read_bytes())[0].name == '祭祀碑牌'
    assert refs.clean_tablet_layer(patched.read_bytes()) == patched.read_bytes()


def test_repeated_restore_keeps_saved_english_bytes_instead_of_recleaning_live_table(tmp_path):
    baseline = synthetic_baseitems()
    priced, _ = m.price_tablet_names(baseline, {'Ritual_Tablet': selected('0.38D')})
    live, _ = m._redirect_tablet_base_items(priced, {'Ritual'})
    english = tmp_path / 'live.dat'
    english.write_bytes(live)
    archive = tmp_path / 'restore.zip'
    key = 'data/balance/baseitemtypes.datc64'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(key, baseline)
    for _ in range(2):
        refs.clean_zip(archive, english)
        with zipfile.ZipFile(archive) as z:
            assert z.read(key) == baseline


def test_restore_refreshes_english_baseline_when_official_structure_changes(tmp_path):
    old = synthetic_baseitems()
    current = old.replace('RitualAugment'.encode('utf-16-le'), 'TempleAugment'.encode('utf-16-le'))
    english = tmp_path / 'current.dat'
    english.write_bytes(current)
    archive = tmp_path / 'restore.zip'
    key = 'data/balance/baseitemtypes.datc64'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(key, old)
    refs.clean_zip(archive, english)
    with zipfile.ZipFile(archive) as z:
        assert z.read(key) == current


@pytest.mark.parametrize('row,new_name', [(0, 'New Ritual Tablet'), (2, 'New Exalted Orb')])
@pytest.mark.parametrize('append', [False, True])
def test_restore_refreshes_official_name_changes_without_structure_changes(tmp_path, row, new_name, append):
    old = synthetic_baseitems()
    entry = names.scan_base_item_names(old)[row]
    current = bytearray(old)
    if append:
        offset = len(current) - names.detect_base_item_layout(old).string_base
        struct.pack_into('<I', current, entry.name_pointer_pos, offset)
        current.extend((new_name + '\0').encode('utf-16-le'))
    else:
        # Same-length official string edit leaves every pointer unchanged.
        current[entry.name_start:entry.name_end] = ('新' * len(entry.name)).encode('utf-16-le')
    current = bytes(current)
    assert names.build_structure_signature(old) == names.build_structure_signature(current)
    english = tmp_path / 'current.dat'
    english.write_bytes(current)
    archive = tmp_path / 'restore.zip'
    key = 'data/balance/baseitemtypes.datc64'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(key, old)
    refs.clean_zip(archive, english)
    with zipfile.ZipFile(archive) as z:
        assert z.read(key) == current


def test_original_breach_typo_is_removed_from_priced_and_fallback_lines(tmp_path):
    source = tmp_path/'breach.csd'
    source.write_text('description\n\t1 map_unstable_breach_enrage_x_additional_rare_monsters\n\t2\n'
        '\t\t1 "Unstable Breaches in Map spawn an additional Rare Monster when stabilised"\n'
        '\t\t# "Unstable Breaches in Map spawn {0} additional Rare Monsters when stabilised"\n'
        '\tlang "Traditional Chinese"\n\t2\n'
        '\t\t1 "地圖內的不穩定[ContainsBreach|裂痕]會在穩定後生成一名額外[Rarity|稀有]怪物]"\n'
        '\t\t# "地圖內的不穩定[ContainsBreach|裂痕]會在穩定後生成{0}名額外[Rarity|稀有]怪物]" canonical_line\n', encoding='utf-8')
    result, matched, _ = m._append_tablet_price_to_csd(source,
        [m.Quote('Unstable Breaches in Map spawn (1-2) additional Rare Monsters when stabilised',Decimal(500),1,2)], Decimal(500))
    text = result.decode()
    assert matched == 1 and '怪物]' not in text
    assert '[ContainsBreach|裂痕]' in text and '[Rarity|稀有]' in text
    assert text.count('=1.00D') == 4
    assert '怪物" canonical_line' in text
    assert m.clean_chinese_markup(text) == text
    m.validate_csd(text)


def test_all_affix_lines_are_priced_in_shared_magic_and_rare_descriptions(tmp_path):
    # Rarity is enabled by the shared IT template; CSD matches individual stats,
    # so multiple affixes must all survive generation instead of stopping at one.
    source = tmp_path/'all-affixes.csd'
    stats = [('rarity', 'Monster Rarity', '怪物稀有度'),
             ('effect', 'Monster Effectiveness', '怪物效用'),
             ('quantity', 'Quantity of Items', '物品数量')]
    text = ''.join(csd().replace('test_stat', stat).replace('Monster Rarity', english)
                   .replace('怪物稀有度', chinese) for stat, english, chinese in stats)
    source.write_bytes(text.encode())
    quotes = [m.Quote(f'Map has (15-20)% increased {english}', Decimal(500 * (i+1)),15,20)
              for i,(_,english,_) in enumerate(stats)]
    result, matched, _ = m._append_tablet_price_to_csd(source,quotes,Decimal(500))
    assert matched == 3
    output = result.decode()
    for i,(_,_,chinese) in enumerate(stats):
        assert f'{chinese}]={i+1:.2f}D' in output
    m.validate_csd(output)


@pytest.mark.parametrize('old_magic', [False, True])
@pytest.mark.parametrize('statistic', ['low_sample_median', 'min'])
@pytest.mark.parametrize('english_target', [False, True])
@pytest.mark.parametrize('old_all', [False, True])
def test_pair_medians_install_into_one_description_with_game_stat_mapping(tmp_path, old_magic, statistic, english_target, old_all):
    class SplitClient:
        def __init__(self):
            self.urls = []

        def get_json(self, url):
            self.urls.append(url)
            if 'poe.ninja' in url:
                return {'core': {'primary': 'divine', 'rates': {'exalted': 500}}, 'lines': [
                    {'baseType': 'Ritual Tablet', 'variant': 'Normal', 'primaryValue': 1,
                     'listingCount': 10, 'corrupted': False}]}
            rarity = parse_qs(urlparse(url).query)['rarity'][0]
            row = quote(text='Map has (15-20)% increased Monster Rarity',
                        price=500 if rarity == 'magic' else 1000)
            row['converted'][statistic] = row['converted'].pop('low_sample_median')
            payload = page([row], rarity=rarity)
            payload['server'] = 'international'; payload['category'] = 'tablet'; payload['rarity'] = rarity
            payload['snapshot']['config']['rarity'] = rarity
            payload['snapshot']['stale'] = old_all or old_magic and rarity == 'magic'
            payload['exchange_rates']['stale'] = old_all
            return payload

    english = tmp_path / 'english.dat'
    legacy, _ = m.price_tablet_names(synthetic_baseitems(english=True), {'Ritual_Tablet':selected('0.24D')})
    english.write_bytes(legacy)
    source = tmp_path / 'base.dat'; source.write_bytes(legacy if english_target else synthetic_baseitems())
    game_path = refs.ENGLISH_BASEITEMS if english_target else 'data/balance/traditional chinese/baseitemtypes.datc64'
    patched = tmp_path / 'patched.dat'; patched.write_bytes(source.read_bytes())
    template = tmp_path / 'template.it'
    template.write_text('Mods\n{\nstat_description_list = "Data/StatDescriptions/tablet_stat_descriptions.csd"\n'
                        'enable_rarity = "normal"\nenable_rarity = "magic"\nenable_rarity = "rare"\n'
                        'enable_rarity = "unique"\n}\n', encoding='utf-8')
    descriptions = tmp_path / 'tablet.csd'; descriptions.write_bytes(csd().encode())
    archive = tmp_path / 'patch.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(game_path, source.read_bytes())

    client = SplitClient()
    report = m.build_tablet_affix_resources(
            client=client, api_base='http://example.invalid', league=LEAGUE,
            template_it=template, template_csd=descriptions,
            source_baseitems=source, patched_baseitems=patched,
            output_zip=archive,
            game_path=game_path,
            english_baseitems=source if english_target else english,
            resource_report=tmp_path / 'report.json',
            **game_tables(tmp_path),
        )
    report = json.loads((tmp_path/'report.json').read_text(encoding='utf-8'))
    queries = [parse_qs(urlparse(url).query).get('rarity', [''])[0] for url in client.urls
               if '/api/v1/prices?' in url]
    assert queries == ['magic', 'rare']
    assert report['status'] == 'partial'
    assert report['game_coverage']['missing_quotes'][0]['tablet'] == 'Breach_Tablet'
    assert report['api']['rarities']['magic']['status'] == report['api']['rarities']['rare']['status'] == 'ok'
    assert report['api']['rarities']['magic']['snapshot_stale'] is (old_magic or old_all)
    assert report['api']['rarities']['rare']['exchange_rates_stale'] is old_all
    assert report['quote_validation']['minimum_price'] == (['one'] if statistic == 'min' else [])
    assert report['resources'][0]['matched'] == 1 and report['redirected_items'] == 1
    assert report['game_mapping'][0]['stat'] == 'test_stat'
    with zipfile.ZipFile(archive) as z:
        refs.validate_resources({p:z.read(p) for p in z.namelist()})
        english_data = z.read(refs.ENGLISH_BASEITEMS)
        assert [e.name for e in names.scan_base_item_names(english_data)] == [
            'Ritual Tablet', 'Breach Tablet', 'Exalted Orb']
        layout = names.detect_base_item_layout(english_data)
        pointer = struct.unpack_from('<Q', english_data, 4 + 40)[0]
        assert names.read_string_offset(english_data, layout, pointer)[0] == 'Metadata/Items/TowerAugments/Poe2Price/Ritual'
        if not english_target:
            assert names.scan_base_item_names(z.read(game_path))[0].name == '[1.00D|祭祀碑牌]'
        text = z.read('data/statdescriptions/poe2price/ritual_tablet_stat_descriptions.csd').decode()
        it = z.read('metadata/items/toweraugments/poe2price/ritual.it').decode()
        assert text.count('=1~2D') == 2
        assert it.count('stat_description_list') == 1
        assert '魔法价格' not in text and '稀有价格' not in text


@pytest.mark.parametrize('returned', ['rare', None])
def test_magic_request_rejects_wrong_or_unidentified_rarity(returned):
    response = page([quote()], rarity=returned)
    with pytest.raises(ValueError, match='rarity'):
        m.fetch_tablet_affix_prices(Client({0:response}), 'http://example.invalid', LEAGUE, rarity='magic')


def test_resource_validation_rejects_repeated_single_description_field():
    redirected, _ = m._redirect_tablet_base_items(synthetic_baseitems(), {'Ritual'})
    entries = {
        'data/balance/baseitemtypes.datc64': redirected,
        'metadata/items/toweraugments/poe2price/ritual.it': (
            'Mods\n{\nstat_description_list = "magic.csd"\n'
            'stat_description_list = "rare.csd"\n'
            'enable_rarity = "magic"\nenable_rarity = "rare"\n}\n').encode(),
        'magic.csd': csd().encode(), 'rare.csd': csd().encode(),
    }
    with pytest.raises(ValueError, match='repeats a single stat_description_list'):
        refs.validate_resources(entries)


@pytest.mark.parametrize('rare,magic,expected', [
    ('5','16','5~16D'), ('16','5','5~16D'),
    ('0.05','0.06','5.5E'), ('0.06','0.05','5.5E'),
    ('0.05','0.16','5~16E'), ('1','1','100E'),
    ('5','5.5','5.25D'), ('5','5.51','5~5.51D'),
])
def test_dual_price_order_and_shared_currency(rare, magic, expected):
    rates = {'divine':Decimal(1), 'chaos':Decimal('.1'), 'exalted':Decimal('.01')}
    label, _ = m.format_pair(Decimal(rare), Decimal(magic), rates,
                             (Decimal('.06'), Decimal('.12')), {'exalted':20})
    assert label == expected


def test_market_scaling_does_not_change_merge_decisions():
    from poe2_tablet_display import market_anchors, format_pair
    pairs = [(Decimal(a), Decimal(b)) for a,b in [('5','6'), ('6','7'), ('11','13'), ('16','17')]]
    decisions = []
    for factor in map(Decimal, ['.01','.1','1','10','100']):
        scaled = [(a*factor,b*factor) for a,b in pairs]
        anchors = market_anchors(scaled)
        decisions.append([format_pair(a,b,{'divine':Decimal(1)},anchors)[1]['merged'] for a,b in scaled])
    assert all(row == decisions[0] for row in decisions)


def test_query_mismatch_is_excluded_from_both_price_and_market_anchors():
    from dataclasses import replace
    q = m.Quote('Map contains 1 additional Strongboxes',Decimal(10),1,1,identifier='a',query_scope='same')
    expensive = replace(q, identifier='b', price=Decimal(1_000_000), query_scope='different')
    info = {rarity:{'rates':{'exalted':'.002','chaos':'.1'}} for rarity in ('rare','magic')}
    result, audit = m.pair_tablet_quotes({'rare':{'Ritual_Tablet':[q,expensive]},
        'magic':{'Ritual_Tablet':[q,replace(expensive,query_scope='other')]}},info)
    assert [quote.identifier for quote in result['Ritual_Tablet']] == ['a']
    assert next(row for row in audit if row['id']=='b')['status'] == 'excluded'
    assert Decimal(next(row for row in audit if row['id']=='a')['policy']['low_anchor_divine']) == Decimal('.02')


def test_trade_query_scope_preserves_filters_and_validates_rarity():
    assert m.trade_query_scope(trade_url('one','rare'),'rare') == m.trade_query_scope(trade_url('one','magic'),'magic')
    assert m.trade_query_scope(trade_url('one','rare'),'magic') == ''
    assert m.trade_query_scope(trade_url('one','rare'),'rare') != m.trade_query_scope(trade_url('two','rare'),'rare')


def test_tablet_price_prefers_medians_and_falls_back_to_minimum():
    assert m._tablet_price_details({'converted':{'currency':'exalted','min':10}}) == (10, 'min')
    assert m._tablet_price_details({'prices':{'exalted':{'min':10}}}) == (10, 'min')
    assert m._tablet_price_from_row({'converted':{'currency':'exalted','median':30,'min':10}}) == 30
    assert m._tablet_price_from_row({'converted':{'currency':'exalted','low_sample_median':25,'min':10}}) == 25


def test_raw_minimum_converts_all_currencies_but_never_uses_partial_conversion():
    rates = {'exalted':Decimal('.002'), 'divine':Decimal(1)}
    row = {'prices':{'exalted':{'min':100},'divine':{'min':Decimal('.1')}}}
    assert m._tablet_price_details(row, rates) == (50, 'min')
    row['prices']['unknown'] = {'min':1}
    assert m._tablet_price_from_row(row, rates) == 0
    row['converted'] = {'currency':'exalted','min':10,'missing_count':1}
    assert m._tablet_price_from_row(row, rates) == 0
    assert m._tablet_price_details({'converted':{'currency':'exalted','min':10},
        'prices':{'exalted':{'median':30}}}) == (30, 'median')


@pytest.mark.parametrize('rarity', ['magic', 'rare'])
def test_same_league_cache_recovers_api_outage_and_keeps_original_sampling_dates(tmp_path, rarity):
    payload = page([quote()], rarity=rarity)
    payload['snapshot']['published_at'] = '2026-09-22T07:09:35+00:00'
    _, fresh = m.fetch_tablet_affix_prices(Client({0:payload}), 'http://example.invalid', LEAGUE,
        rarity=rarity, cache_dir=tmp_path)
    assert fresh['source'] == 'live'
    cache_path = next(tmp_path.glob('*.json')); saved = cache_path.read_bytes()
    class Offline:
        def get_json(self, url): raise ConnectionError('offline after HTTP retries')
    notices = []
    prices, cached = m.fetch_tablet_affix_prices(Offline(), 'http://example.invalid', LEAGUE,
        rarity=rarity, cache_dir=tmp_path, on_retry=notices.append)
    assert prices['Ritual_Tablet'][0].price == 500
    assert cached['source'] == 'cache' and cached['freshness'] == 'last_successful_snapshot'
    assert cached['published_at'] == payload['snapshot']['published_at']
    assert cached['cache_saved_at'] and 'ConnectionError' in cached['live_error']
    assert len(notices) == 1 and cache_path.read_bytes() == saved
    with pytest.raises(ConnectionError):
        m.fetch_tablet_affix_prices(Offline(), 'http://example.invalid', 'Standard',
            rarity=rarity, cache_dir=tmp_path)
    with pytest.raises(ConnectionError):
        m.fetch_tablet_affix_prices(Offline(), 'http://other.invalid', LEAGUE,
            rarity=rarity, cache_dir=tmp_path)


def test_cache_is_revalidated_and_cannot_mix_leagues_or_pages(tmp_path):
    payload = page([quote()])
    m.fetch_tablet_affix_prices(Client({0:payload}), 'http://example.invalid', LEAGUE, cache_dir=tmp_path)
    cache_path = next(tmp_path.glob('*.json')); cached = json.loads(cache_path.read_text())
    next(iter(cached['pages'].values()))['snapshot']['league'] = 'Standard'
    cache_path.write_text(json.dumps(cached), encoding='utf-8')
    class Offline:
        def get_json(self, url): raise ConnectionError('offline')
    with pytest.raises(ValueError, match='cached snapshot rejected.*league'):
        m.fetch_tablet_affix_prices(Offline(), 'http://example.invalid', LEAGUE, cache_dir=tmp_path)


def test_different_rate_revisions_convert_each_price_before_pairing():
    q = m.Quote('Map contains 1 additional Strongboxes',Decimal(100),1,1,
                identifier='a', query_scope='same')
    info = {'rare':{'rates':{'exalted':'.002','chaos':'.1'},'source':'live'},
            'magic':{'rates':{'exalted':'.004','chaos':'.2'},'source':'cache'}}
    _, audit = m.pair_tablet_quotes({'rare':{'Ritual_Tablet':[q]},'magic':{'Ritual_Tablet':[q]}},info)
    row = audit[0]
    assert Decimal(row['rare_divine']) == Decimal('.2')
    assert Decimal(row['magic_divine']) == Decimal('.4')
    assert row['label'] == '2~4C'


def test_pairing_requires_identical_ids_and_modifier_details():
    from dataclasses import replace
    q = m.Quote('Map contains 1 additional Strongboxes',Decimal(10),1,1,identifier='a')
    info = {rarity:{'rates':{'exalted':'0.002','chaos':'0.1'}} for rarity in ('magic','rare')}
    q = replace(q, query_scope='same')
    _, audit = m.pair_tablet_quotes({'rare':{'Ritual_Tablet':[q]},
        'magic':{'Ritual_Tablet':[replace(q,identifier='b')]}},info)
    assert [(r['id'],r['price_rarities']) for r in audit] == [('a',['rare']),('b',['magic'])]
    with pytest.raises(ValueError,match='identities'):
        m.pair_tablet_quotes({'rare':{'Ritual_Tablet':[q]},'magic':{'Ritual_Tablet':[replace(q,text='Map contains 2 additional Strongboxes')]}},info)


def test_similar_text_on_different_stats_does_not_receive_the_same_pair():
    q = m.Quote('Map has (15-20)% increased Monster Rarity',Decimal(500),15,20,
                stat='test_stat',label='1~2D')
    other = csd().replace('test_stat','different_stat')
    text, used, changed = m.price_block(other,[q],Decimal(500))
    assert text == other and not used and not changed


def test_wrong_game_modifier_identity_is_rejected(tmp_path):
    from poe2_tablet_catalog import bind_game_stats
    files = game_tables(tmp_path)
    source = tmp_path/'base.dat'; source.write_bytes(synthetic_baseitems())
    q = m.Quote('Map has (15-20)% increased Monster Rarity',Decimal(500),15,20,
                identifier='a',name='Unknown modifier',generation='prefix')
    with pytest.raises(ValueError,match='identity is not unique'):
        bind_game_stats({'Ritual_Tablet':[q]},mods_path=files['tablet_mods'],
                        stats_path=files['tablet_stats'],tags_path=files['tablet_tags'],baseitems_path=source)


@pytest.mark.parametrize('condition,tail,raw_range', [
    ('1|#', '', (8, 12)), ('#|-1', ' negate 1', (-12, -8)),
    ('1|#', ' divide_by_one_hundred 1', (800, 1200)),
])
def test_cn_v79_default_chinese_uses_bound_raw_stat_range(condition, tail, raw_range):
    from poe2_tablet_catalog import bind_game_stats
    # The market text's leading 10 and fixed cap 100 are not the raw stat range.
    q = m.Quote('After 10 seconds grants (8-12)% Effectiveness, up to 100%', Decimal(500),
                10, 10, identifier='cn-default', name='test_mod', generation='prefix')
    bound, _ = bind_game_stats({'Ritual_Tablet':[q]}, game_catalog=[{
        'tablet':'Ritual_Tablet', 'generation':'prefix', 'name':'测试', 'mod_id':'test_mod',
        'stat':'test_stat', 'range':list(raw_range),
    }])
    block = ('description\n\t1 test_stat\n\t1\n'
             f'\t\t{condition} "<AT1>{{{{十秒后效能增加{{0}}%，最多100%}}}}"{tail}\n')
    output, used, _ = m.price_block(block, bound['Ritual_Tablet'], Decimal(500))
    assert used == {'cn-default'} and 'lang "' not in output
    m.validate_csd(output)
    records = [r for line in output.splitlines(keepends=True) if (r := m.LINE.match(line))]
    lo, hi = sorted(raw_range)
    for value in range(lo-1, hi+2):
        first = next(r for r in records if
            (m.condition_bounds(r[2])[0] is None or m.condition_bounds(r[2])[0] <= value) and
            (m.condition_bounds(r[2])[1] is None or value <= m.condition_bounds(r[2])[1]))
        assert first[3].endswith('=1.00D') == (lo <= value <= hi)
        assert first[3].startswith('<AT1>{{十秒后效能增加{0}%，最多100%}}')
        assert first[4] == tail
    # No translated-text guessing without current game identity and range.
    assert m.price_block(block, [q], Decimal(500))[1] == set()
    assert m.price_block(block, [m.replace(bound['Ritual_Tablet'][0], stat='other')], Decimal(500))[1] == set()
    assert m.price_block(block.replace(tail+'\n', ' unknown_transform 1\n'), bound['Ritual_Tablet'], Decimal(500))[1] == set()


def test_cn_v79_coloured_default_branches_keep_first_match_semantics():
    block = 'description\n\t1 test_stat\n\t4\n'
    for condition, style in [('1','AT3'),('2','AT2'),('3','AT1'),('#','AT1')]:
        block += f'\t\t{condition} "<{style}>{{{{额外生成{{0}}只稀有怪物}}}}"\n'
    q = m.Quote('irrelevant translation', Decimal(500), identifier='bound', stat='test_stat', game_range=(1,2))
    output, used, _ = m.price_block(block, [q], Decimal(500))
    assert used == {'bound'}
    m.validate_csd(output)
    records = [r for line in output.splitlines(keepends=True) if (r := m.LINE.match(line))]
    for value in [0,1,2,3,4]:
        r = next(r for r in records if m.condition_bounds(r[2]) == (None,None) or
            m.condition_bounds(r[2])[0] <= value <= m.condition_bounds(r[2])[1])
        assert r[3].endswith('=1.00D') == (value in [1,2])


@pytest.mark.parametrize('rarity', ['magic', 'rare'])
def test_stale_market_and_rates_remain_usable_and_live_data_replaces_cache(tmp_path, rarity):
    old = page([quote(price=500)], rarity=rarity)
    old['snapshot'].update(stale=True, published_at='2026-09-22T07:09:35+00:00')
    old['exchange_rates'].update(stale=True, source_updated_at='2026-09-22T06:00:00+00:00')
    prices, report = m.fetch_tablet_affix_prices(Client({0:old}), 'http://test.invalid', LEAGUE,
        rarity=rarity, allow_stale=True, cache_dir=tmp_path)
    assert prices['Ritual_Tablet'][0].price == 500
    assert report['source'] == 'live' and report['snapshot_stale'] and report['exchange_rates_stale']
    assert report['exchange_rates_updated_at'] == '2026-09-22T06:00:00+00:00'
    new = page([quote(price=750)], rarity=rarity)
    new['snapshot']['published_at'] = '2026-09-26T07:00:00+00:00'
    prices, report = m.fetch_tablet_affix_prices(Client({0:new}), 'http://test.invalid', LEAGUE,
        rarity=rarity, allow_stale=True, cache_dir=tmp_path)
    assert prices['Ritual_Tablet'][0].price == 750 and report['source'] == 'live'
    assert not report['snapshot_stale'] and not report['exchange_rates_stale']
    class Offline:
        def get_json(self, url): raise OSError('offline')
    prices, report = m.fetch_tablet_affix_prices(Offline(), 'http://test.invalid', LEAGUE,
        rarity=rarity, allow_stale=True, cache_dir=tmp_path)
    assert prices['Ritual_Tablet'][0].price == 750 and report['source'] == 'cache'
    with pytest.raises(OSError):
        m.fetch_tablet_affix_prices(Offline(), 'http://test.invalid', 'Wrong season',
            rarity=rarity, allow_stale=True, cache_dir=tmp_path)


@pytest.mark.parametrize('section,field,value', [
    ('snapshot','league','other'), ('exchange_rates','league','other'),
    ('snapshot','stale',None), ('exchange_rates','stale',None),
    ('snapshot','id','changed'),
])
def test_allow_stale_does_not_allow_unknown_health_wrong_league_or_mixed_pages(section, field, value):
    first=page([quote()], total=2);second=page([quote('two')],offset=1,total=2)
    first['snapshot']['stale']=second['snapshot']['stale']=True
    first['exchange_rates']['stale']=second['exchange_rates']['stale']=True
    second[section][field]=value
    with pytest.raises(ValueError):
        m.fetch_tablet_affix_prices(Client({0:first,1:second}), 'http://test.invalid',LEAGUE,allow_stale=True)
