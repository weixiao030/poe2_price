from decimal import Decimal
from pathlib import Path
import struct
import sys
from urllib.parse import parse_qs, urlparse
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "物价补丁/tools"))
import poe2_tablet_prices as m
import poe2_name_price_patch as names
import poe2_tablet_refs as refs

LEAGUE = "Forbidden Rites"


def synthetic_baseitems():
    metadata = ["Metadata/Items/TowerAugment/RitualAugment", "Metadata/Items/TowerAugment/BreachAugment", "Metadata/Items/Currency/CurrencyAddModToRare"]
    rows = bytearray(4 + len(metadata) * 360)
    struct.pack_into("<I", rows, 0, len(metadata))
    strings = bytearray()

    def add(text):
        at = len(strings)
        strings.extend((text + "\0").encode("utf-16-le"))
        return at

    for i, text in enumerate(metadata):
        at = 4 + i * 360
        struct.pack_into("<Q", rows, at, add(text))
        struct.pack_into("<Q", rows, at + 32, add(["祭祀碑牌", "裂痕碑牌", "崇高石"][i]))
        struct.pack_into("<Q", rows, at + 40, add(refs.ORIGINAL))
    return bytes(rows + strings)


def quote(identifier="one", text="Map has (15-20)% increased Monster Rarity", price=500):
    return {"id": identifier, "tablet": "Ritual_Tablet", "text_en": text, "status": "ok", "sample_count": 10,
            "converted": {"currency": "exalted", "low_sample_median": price, "missing_count": 0}}


def page(rows, offset=0, total=None):
    return {"snapshot": {"id": "snapshot", "league": LEAGUE, "stale": False, "config": {"min_uses": 10}},
            "exchange_rates": {"league": LEAGUE, "stale": False, "primary": "divine", "values": {"exalted": 0.002, "chaos": 0.1}},
            "offset": offset, "total": len(rows) if total is None else total, "data": rows}


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


def test_bad_status_and_partial_currency_conversion_are_not_quotes():
    bad = quote(); bad["status"] = "error"
    partial = quote("partial"); partial["converted"]["missing_count"] = 1
    prices, _ = m.fetch_tablet_affix_prices(Client({0:page([bad, partial])}), "http://example.invalid", LEAGUE)
    assert prices == {}


@pytest.mark.parametrize("unit,amount,expected", [("divine", 5, "2500"), ("chaos", 5, "250"), ("exalted", 5, "5")])
def test_raw_currency_conversion(unit, amount, expected):
    assert m._tablet_price_from_row({"prices":{unit:{"min":amount}}}, {"divine":Decimal(1), "exalted":Decimal("0.002"), "chaos":Decimal("0.1")}) == Decimal(expected)


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


def test_sources_fail_independently_and_zero_match_cannot_succeed(tmp_path):
    source = tmp_path / "base.dat"; source.write_bytes(synthetic_baseitems())
    patched = tmp_path / "patched.dat"; patched.write_bytes(source.read_bytes())
    template = tmp_path / "template.it"; template.write_text('Mods\n{\nstat_description_list = "Data/StatDescriptions/tablet_stat_descriptions.csd"\n}\n', encoding='utf-8')
    descriptions = tmp_path / "tablet.csd"; descriptions.write_bytes(csd().encode('utf-8'))
    archive = tmp_path / "patch.zip"
    with zipfile.ZipFile(archive, 'w') as z: z.writestr('data/balance/traditional chinese/baseitemtypes.datc64', source.read_bytes())
    class Partial:
        def get_json(self, url):
            if 'poe.ninja' in url: raise TimeoutError('offline')
            return page([quote()])
    args = dict(client=Partial(),api_base='http://example.invalid',league=LEAGUE,template_it=template,template_csd=descriptions,source_baseitems=source,patched_baseitems=patched,output_zip=archive,game_path='data/balance/traditional chinese/baseitemtypes.datc64',resource_report=tmp_path/'report.json')
    report = m.build_tablet_affix_resources(**args)
    assert report['status'] == 'partial'
    assert report['poe_ninja_precursor_tablets']['status'] == 'unavailable'
    before = archive.read_bytes()
    descriptions.write_bytes(csd().replace('Monster Rarity', 'Unrelated Text').encode('utf-8'))
    with pytest.raises(ValueError, match='no tablet descriptions matched'):
        m.build_tablet_affix_resources(**args)
    assert archive.read_bytes() == before


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
def test_ninja_only_and_both_sources_offline_leave_valid_core(tmp_path, templates_available):
    source = tmp_path/'base.dat'; source.write_bytes(synthetic_baseitems())
    patched = tmp_path/'patched.dat'; patched.write_bytes(source.read_bytes())
    template = tmp_path/'template.it'
    template.write_text('Mods\n{\nstat_description_list = "Data/StatDescriptions/tablet_stat_descriptions.csd"\nenable_rarity = "magic"\nenable_rarity = "rare"\n}\n', encoding='utf-8')
    descriptions = tmp_path/'tablet.csd'; descriptions.write_bytes(csd().encode())
    if not templates_available:
        template.unlink(); descriptions.unlink()
    english = tmp_path/'english.dat'; english.write_bytes(source.read_bytes())
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
    assert report['base_names'] == [{'tablet':'Ritual_Tablet', 'price':'1.00D', 'variant':'Normal'}]
    for path in [core_path, 'data/balance/baseitemtypes.datc64']:
        assert names.scan_base_item_names(entries[path])[0].name == '祭祀碑牌=1.00D'
    class Offline:
        def get_json(self, url): raise TimeoutError('offline')
    args['client'] = Offline()
    before = archive.read_bytes(); before_dat = patched.read_bytes()
    with pytest.raises(ValueError, match='sources unavailable'):
        m.build_tablet_affix_resources(**args)
    assert archive.read_bytes() == before and patched.read_bytes() == before_dat


def test_names_use_exact_base_paths_update_and_skip_missing_normal():
    original = synthetic_baseitems()
    unrelated, _ = names.build_replacements(names.scan_base_item_names(original),
        [{'metadata_path':'Metadata/Items/Currency/CurrencyAddModToRare','new_name':'崇高石=2D'}], '=', False, 'append', False)
    original = names.apply_replacements_append(original, unrelated)
    priced, rows = m.price_tablet_names(original, {'Ritual_Tablet':{'Normal':'0.38D','Rare':'9.00D'},
                                                'Breach_Tablet':{'Rare':'5.00D'}})
    assert [e.name for e in names.scan_base_item_names(priced)] == ['祭祀碑牌=0.38D', '裂痕碑牌', '崇高石=2D']
    assert len(rows) == 1
    updated, _ = m.price_tablet_names(priced, {'Ritual_Tablet':{'Normal':'0.40D'}})
    assert names.scan_base_item_names(updated)[0].name == '祭祀碑牌=0.40D'
    assert m.price_tablet_names(updated, {'Ritual_Tablet':{'Normal':'0.40D'}})[0] == updated
    cleaned = refs.clean_tablet_layer(updated)
    assert [e.name for e in names.scan_base_item_names(cleaned)] == ['祭祀碑牌', '裂痕碑牌', '崇高石=2D']
    assert refs.clean_tablet_layer(cleaned) == cleaned
    assert names.build_structure_signature(priced) == names.build_structure_signature(original)


def test_api_available_without_templates_still_updates_ninja_names(tmp_path):
    source = tmp_path/'source.dat'; source.write_bytes(synthetic_baseitems())
    patched = tmp_path/'patched.dat'; patched.write_bytes(source.read_bytes())
    archive = tmp_path/'patch.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('data/balance/baseitemtypes.datc64', source.read_bytes())
        z.writestr('metadata/items/toweraugments/poe2price/ritual.it', b'old')
    class Both:
        def get_json(self, url):
            if 'poe.ninja' not in url: return page([quote()])
            return {'core':{'primary':'divine','rates':{'exalted':500}},'lines':[
                {'baseType':'Ritual Tablet','variant':'Normal','primaryValue':1,'listingCount':10,'corrupted':False}]}
    report = m.build_tablet_affix_resources(client=Both(),api_base='http://unused',league=LEAGUE,
        template_it=None,template_csd=None,source_baseitems=source,patched_baseitems=patched,
        output_zip=archive,game_path='data/balance/baseitemtypes.datc64',resource_report=tmp_path/'report.json')
    assert report['status'] == 'partial' and report['affix_templates']['status'] == 'unavailable'
    assert report['api']['status'] == report['poe_ninja_precursor_tablets']['status'] == 'ok'
    with zipfile.ZipFile(archive) as z:
        assert z.namelist() == ['data/balance/baseitemtypes.datc64']
        assert names.scan_base_item_names(z.read(z.namelist()[0]))[0].name == '祭祀碑牌=1.00D'


def test_restore_and_disabled_build_remove_tablet_name_prices_in_both_languages(tmp_path):
    priced, _ = m.price_tablet_names(synthetic_baseitems(), {'Ritual_Tablet':{'Normal':'0.38D'}})
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
