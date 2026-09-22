"""Real trade alternative groups must be resolved with the current spawn pool."""
from dataclasses import replace
from decimal import Decimal
import json

from tests.test_tablet_affixes import m
from poe2_tablet_catalog import bind_trade_query

SPIRIT = 'map_spawn_extra_torment_spirits'
BOSS_SPIRIT = 'maps_with_powerful_bosses_additional_spirit_+'
IDS = ['explicit.stat_358129101', 'explicit.stat_775597083']


def quote(ids, uses=10):
    group = ({'type': 'and', 'filters': [{'id': ids[0]}]} if len(ids) == 1 else
             {'type': 'count', 'value': {'min': 1}, 'filters': [{'id': i} for i in ids]})
    scope = ['/trade2/search/poe2/League', {'type': 'Delirium Tablet', 'stats': [group,
             {'type': 'and', 'filters': [{'id': 'implicit.uses', 'value': {'min': uses}}]}]}]
    return m.Quote('Map contains 1 additional Azmeri Spirits', Decimal(10), 1, 1,
                   identifier='spirit', stat=SPIRIT, query_scope=json.dumps(scope))


def pair(rare, magic):
    rates = {r: {'rates': {'exalted': '.002', 'chaos': '.1'}} for r in ('rare', 'magic')}
    return m.pair_tablet_quotes({'rare': {'Delirium_Tablet': [rare]},
                                'magic': {'Delirium_Tablet': [magic]}}, rates)


def test_unspawnable_alternative_is_equivalent_and_both_medians_survive():
    magic = bind_trade_query(quote(IDS), SPIRIT, {SPIRIT})
    rare = bind_trade_query(quote(IDS[:1]), SPIRIT, {SPIRIT})
    assert magic.query_exact and magic.query_scope == rare.query_scope
    result, audit = pair(rare, replace(magic, price=Decimal(30)))
    assert result['Delirium_Tablet'][0].label == '10~30E'
    assert audit[0]['price_rarities'] == ['magic', 'rare']


def test_spawnable_different_modifier_uses_only_the_exact_median():
    available = {SPIRIT, BOSS_SPIRIT}
    magic = bind_trade_query(quote(IDS), SPIRIT, available)
    rare = bind_trade_query(quote(IDS[:1]), SPIRIT, available)
    assert magic.query_exact is False and rare.query_exact is True
    result, audit = pair(rare, replace(magic, price=Decimal(1_000_000)))
    assert result['Delirium_Tablet'][0].label == '10E'
    assert audit[0]['price_rarities'] == ['rare']
    assert Decimal(audit[0]['policy']['low_anchor_divine']) == Decimal('.02')
    result, audit = pair(replace(magic, price=Decimal(1_000_000)), rare)
    assert result['Delirium_Tablet'][0].label == '10E'
    assert audit[0]['price_rarities'] == ['magic']


def test_identical_known_broad_queries_keep_website_reference_price_and_report_scope():
    broad = bind_trade_query(quote(IDS), SPIRIT, {SPIRIT, BOSS_SPIRIT})
    result, audit = pair(broad, replace(broad, price=Decimal(30)))
    assert result['Delirium_Tablet'][0].label == '10~30E'
    assert audit[0]['price_rarities'] == ['magic', 'rare']
    assert 'website reference price' in audit[0]['query_scope_warning']
    assert broad.query_reference and broad.query_exact is False


def test_unknown_or_wrong_modifier_queries_never_become_reference_prices():
    import pytest
    for identifiers in ([IDS[1]], [IDS[0], 'explicit.unknown']):
        invalid = bind_trade_query(quote(identifiers), SPIRIT, {SPIRIT, BOSS_SPIRIT})
        assert not invalid.query_reference
        with pytest.raises(ValueError, match='no tablet pairs'):
            pair(invalid, invalid)


def test_unavailable_rarity_uses_only_the_live_median_without_fabricating_other_prices():
    import pytest
    valid = bind_trade_query(quote(IDS[:1]), SPIRIT, {SPIRIT, BOSS_SPIRIT})
    broad = bind_trade_query(quote(IDS), SPIRIT, {SPIRIT, BOSS_SPIRIT})
    for rarity in ('magic', 'rare'):
        missing = 'rare' if rarity == 'magic' else 'magic'
        for selected in (valid, broad):
            result, audit = m.pair_tablet_quotes({rarity: {'Delirium_Tablet': [selected]}},
                {rarity: {'status': 'ok', 'rates': {'exalted': '.002', 'chaos': '.1'}},
                 missing: {'status': 'unavailable', 'reason': 'snapshot is stale'}})
            assert result['Delirium_Tablet'][0].label == '10E'
            assert audit[0]['price_rarities'] == [rarity]
            assert audit[0][missing + '_divine'] is None
            assert audit[0][rarity + '_divine'] == '0.020'
            assert bool(audit[0]['query_scope_warning']) == selected.query_reference
    unknown = bind_trade_query(quote([IDS[0], 'explicit.unknown']), SPIRIT, {SPIRIT})
    with pytest.raises(ValueError, match='no tablet pairs'):
        m.pair_tablet_quotes({'rare': {'Delirium_Tablet': [unknown]}},
                            {'rare': {'rates': {'exalted': '.002'}}})


def test_alternative_resolution_does_not_drop_use_count_or_unknown_filters():
    a = bind_trade_query(quote(IDS), SPIRIT, {SPIRIT, BOSS_SPIRIT})
    b = bind_trade_query(quote(IDS[:1], uses=5), SPIRIT, {SPIRIT, BOSS_SPIRIT})
    assert a.query_context != b.query_context
    import pytest
    with pytest.raises(ValueError, match='no tablet pairs'):
        pair(b, a)
    unknown = bind_trade_query(quote([IDS[0], 'explicit.unknown']), SPIRIT, {SPIRIT})
    assert unknown.query_exact is False and not unknown.query_context


def test_boss_modifier_remains_distinct_when_both_can_spawn():
    boss = bind_trade_query(quote(IDS[1:]), BOSS_SPIRIT, {SPIRIT, BOSS_SPIRIT})
    regular = bind_trade_query(quote(IDS[:1]), SPIRIT, {SPIRIT, BOSS_SPIRIT})
    assert boss.query_exact and regular.query_exact
    assert boss.query_scope != regular.query_scope


def test_full_game_coverage_keeps_mods_with_no_market_quote(tmp_path):
    from tests.test_tablet_affixes import game_tables, synthetic_baseitems
    from poe2_tablet_catalog import game_affix_catalog, bind_game_stats, report_game_coverage
    paths = game_tables(tmp_path)
    source = tmp_path/'base.dat'; source.write_bytes(synthetic_baseitems())
    catalog = game_affix_catalog(mods_path=paths['tablet_mods'], stats_path=paths['tablet_stats'],
                                tags_path=paths['tablet_tags'], baseitems_path=source)
    # The same mod can roll on both bases, while the source quotes only Ritual.
    q = m.Quote('text', Decimal(10), identifier='one', name="Challenger's", generation='prefix')
    _, mapping = bind_game_stats({'Ritual_Tablet':[q]}, game_catalog=catalog)
    report = report_game_coverage(catalog, mapping)
    assert report['status'] == 'partial'
    assert report['game_combinations'] == 2 and report['quoted_combinations'] == 1
    assert [(row['tablet'], row['mod_id']) for row in report['missing_quotes']] == [('Breach_Tablet','test_mod')]
