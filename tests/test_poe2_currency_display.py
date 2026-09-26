"""Shared display boundaries, exact truncation, ranges and hidden-price rules."""
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from tests.test_whole_tablets import fetch, Client, page, row
import build_poe2scout_price_patch as builder
from poe2_tablet_display import display_number, format_value, format_pair
from poe2_whole_tablets import apply_whole_tablet_display

CN = dict(exalted=Decimal(1), chaos=Decimal(87), divine=Decimal(535))
INTL = dict(exalted=Decimal(1), chaos=Decimal('64.8761408083442'), divine=Decimal('497.6'))


@pytest.mark.parametrize('value,cn,intl', [
    ('5', '5E', '5E'), ('50.5', '50.5E', '50.5E'),
    ('70', '70E', '1.07C'), ('110', '1.26C', '1.69C'),
    ('170', '1.95C', '2.62C'), ('270', '3.1C', '4.16C'),
    ('600', '1.12D', '1.2D'), ('1200', '2.24D', '2.41D'),
])
def test_both_markets_share_display_policy(value, cn, intl):
    assert format_value(Decimal(value), CN) == cn
    assert format_value(Decimal(value), INTL) == intl


@pytest.mark.parametrize('value,expected', [
    ('86.999999999', '86.99E'), ('87', '1C'),
    ('534.999999999', '6.14C'), ('535', '1D'),
    ('1.269', '1.26'), ('1.99999999999', '1.99'),
    ('0.00000999', '0.000009'), ('1000000.999', '1000000.99'),
])
def test_never_rounds_up_or_switches_unit_after_rounding(value, expected):
    actual = format_value(Decimal(value), CN) if expected[-1] in 'ECD' else display_number(Decimal(value))
    assert actual == expected


def test_fraction_truncation_does_not_depend_on_decimal_context():
    with localcontext() as context:
        context.prec = 4
        assert display_number(Fraction(199999999999, 100000000000)) == '1.99'
        assert display_number(Fraction(1, 10**30)) == '0.' + '0' * 29 + '1'


@pytest.mark.parametrize('chaos', ['0.5', '535', '600', '0'])
def test_skip_chaos_outside_currency_ladder(chaos):
    assert format_value(Decimal(110), {**CN, 'chaos': Decimal(chaos)}) == '110E'


@pytest.mark.parametrize('low,high,label', [
    (5, 20, '5~20E'), (80, 170, '80~170E'),
    (110, 270, '1.26~3.1C'), (600, 1200, '1.12~2.24D'),
])
def test_ranges_choose_unit_from_lower_endpoint(low, high, label):
    for a, b in [(low, high), (high, low)]:
        assert format_pair(Decimal(a), Decimal(b), CN, (Decimal(10), Decimal(20)))[0] == label


def observation(identifier, name, amount):
    return builder.PriceObservation(identifier, name, 'currency', Decimal(amount), Decimal(10), 'same market')


def test_currency_names_and_unique_prices_share_rates_and_keep_suppression(tmp_path):
    prices = {o.api_id:o for o in [observation('divine','Divine Orb','535'),
        observation('exalted','Exalted Orb','1'), observation('chaos','Chaos Orb','87'),
        observation('currency','Test Currency','110'), observation('unique:test','Test Unique','170'),
        observation('cheap','Cheap','0.99')]}
    builder.apply_display_prices(prices, Decimal(535))
    assert prices['divine'].display_price == prices['exalted'].display_price == ''
    assert prices['currency'].display_price == '1.26C'
    assert prices['unique:test'].display_price == '1.95C'
    pairs = [builder.BaseItemPair('Metadata/Items/' + o.api_id, o.en_name, o.en_name) for o in prices.values()]
    rows, _ = builder.match_prices_to_base_items(prices, pairs, None, False, 1)
    assert {r['api_id'] for r in rows} == {'chaos', 'currency'}


def test_cn_whole_quotes_and_legendary_names_use_common_rates_without_double_conversion():
    report = fetch(Client(page([row(), row('unique')])))
    for _ in range(2):
        apply_whole_tablet_display(report, CN)
        assert report['base_prices']['Ritual_Tablet']['price'] == '1.14C'
        assert report['unique_prices']['freedom of faith']['price'] == '1.14C'
        assert report['unique_prices']['freedom of faith']['amount'] == '100'
        assert report['base_prices']['Ritual_Tablet']['native_price'] == '100E'


def test_same_market_fallback_and_ninja_share_operation_rates():
    from poe2_tablet_prices import fetch_poe_ninja_precursor_tablets
    prices = {'item': observation('item', 'Test', '100')}
    builder.apply_display_prices(prices, Decimal(500), CN)
    assert prices['item'].display_price == '1.22C'  # 0.2D at 535E/D, 87E/C
    class Ninja:
        def get_json(self, url):
            return {'core': {'primary': 'divine', 'rates': {'exalted': 500, 'chaos': 10}},
                    'lines': [{'baseType': 'Ritual Tablet', 'variant': 'Normal',
                               'primaryValue': .2, 'listingCount': 10, 'corrupted': False}]}
    result = fetch_poe_ninja_precursor_tablets(Ninja(), 'test', display_rates=CN)
    assert result['base_prices']['Ritual_Tablet']['price'] == '1.22C'


def test_merged_sources_retain_native_divine_value_and_input_observations():
    primary = {'divine': observation('divine', 'Divine Orb', '552.51357736'),
               'chaos': observation('chaos', 'Chaos Orb', '70.5404635')}
    secondary = {'divine': observation('divine', 'Divine Orb', '497.6'),
                 'unique:test': observation('unique:test', 'Test', '3437420.8')}
    merged = builder.merge_price_source_results([
        builder.PriceSourceResult('poe2scout', prices=primary),
        builder.PriceSourceResult('poe-ninja', prices=secondary)])
    for _ in range(2):
        builder.apply_display_prices(merged, primary['divine'].price_exalted)
        assert merged['unique:test'].display_price == '6908D'
        assert merged['chaos'].display_price == '1C'
    assert secondary['unique:test'].source_metadata == {}
    assert secondary['unique:test'].price_exalted == Decimal('3437420.8')


def test_chaos_from_secondary_source_uses_shared_divine_basis():
    primary = {'divine': observation('divine', 'Divine Orb', '600')}
    secondary = {'divine': observation('divine', 'Divine Orb', '500'),
                 'chaos': observation('chaos', 'Chaos Orb', '50')}
    merged = builder.merge_price_source_results([
        builder.PriceSourceResult('poe2scout', prices=primary),
        builder.PriceSourceResult('poe-ninja', prices=secondary)])
    assert builder.price_display_rates(merged, Decimal(600))['chaos'] == 60
    builder.apply_display_prices(merged, Decimal(600))
    assert merged['chaos'].display_price == '1C'
