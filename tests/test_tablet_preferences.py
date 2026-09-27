"""Disabling names must retain affixes, and disabling affixes must retain names."""
from decimal import Decimal
import zipfile

import pytest
from tests.test_tablet_affixes import (
    synthetic_baseitems, csd, game_tables, page, quote, LEAGUE, names, refs, m,
)
from tests.test_whole_tablets import words_fixture
import build_poe2scout_price_patch as builder


def test_affix_only_never_fetches_or_writes_name_prices(tmp_path):
    source = tmp_path / 'source.dat'
    source.write_bytes(synthetic_baseitems())
    patched = tmp_path / 'patched.dat'
    patched.write_bytes(source.read_bytes())
    template = tmp_path / 'template.it'
    template.write_text('Mods\n{\nstat_description_list = "Data/StatDescriptions/tablet_stat_descriptions.csd"\n}\n', encoding='utf-8')
    descriptions = tmp_path / 'tablet.csd'
    descriptions.write_bytes(csd().encode('utf-8'))
    target = 'data/balance/traditional chinese/baseitemtypes.datc64'
    archive = tmp_path / 'patch.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(target, source.read_bytes())

    class AffixesOnly:
        def get_json(self, url):
            from urllib.parse import parse_qs, urlparse
            assert 'poe.ninja' not in url, 'disabled name market must not be queried'
            return page([quote()], rarity=parse_qs(urlparse(url).query)['rarity'][0])

    report = m.build_tablet_affix_resources(
        client=AffixesOnly(), api_base='http://unused', league=LEAGUE,
        template_it=template, template_csd=descriptions, source_baseitems=source,
        patched_baseitems=patched, output_zip=archive, game_path=target,
        resource_report=tmp_path / 'report.json', include_base_prices=False,
        **game_tables(tmp_path),
    )
    assert report['resources'] and not report['base_names']
    assert names.scan_base_item_names(patched.read_bytes())[0].name == '祭祀碑牌'
    with zipfile.ZipFile(archive) as z:
        entries = {key: z.read(key) for key in z.namelist()}
    refs.validate_resources(entries)
    assert any('/poe2price/' in key for key in entries)
    # Adding independent names preserves the already-installed affix references.
    pointers = patched.read_bytes()[44:52]
    builder.apply_cn_whole_tablet_names(patched, archive, target,
        {'base_prices': {'Ritual_Tablet': {'price': '2D'}}})
    assert patched.read_bytes()[44:52] == pointers
    assert names.scan_base_item_names(patched.read_bytes())[0].name == '[2D|祭祀碑牌]'


@pytest.mark.parametrize('china', [False, True])
def test_disabling_tablet_names_removes_old_unique_labels_even_when_feed_contains_prices(tmp_path, china):
    source, output = tmp_path / 'source.dat', tmp_path / 'output.dat'
    words_fixture(source, '[8D|字体补丁译名]')
    unique_names = {'freedomoffaith': builder.UniqueName(0, 'Freedom of Faith', '字体补丁译名')}
    obs = builder.PriceObservation('unique:freedomoffaith', 'Freedom of Faith', 'UniqueTablets',
        Decimal(100), Decimal(10), 'fixture', '5C')
    kwargs = dict(tc_words_path=source, unique_names=unique_names, patched_words=output,
                  excluded_names={'freedomoffaith'})
    if china:
        count, rows, *_ = builder.patch_unique_word_prices_with_cn_fallback(
            **kwargs, primary_prices={}, fallback_prices={obs.api_id: obs},
            tablet_prices={'freedom of faith': {'price': '8D'}},
        )
    else:
        count, rows, _ = builder.patch_unique_word_prices(**kwargs, prices={obs.api_id: obs})
    assert count == 0 and rows[0]['status'] == 'cleaned'
    data = output.read_bytes()
    assert builder.read_words_row(data, builder.detect_words_layout(data), 0).display_name == '字体补丁译名'
