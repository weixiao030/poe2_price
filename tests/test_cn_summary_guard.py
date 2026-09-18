"""Regression cases for ordinary-summary OCR filtering, without network access."""
from decimal import Decimal
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '物价补丁' / 'tools'))
from price_sources.poecurrency_pricing import select_price
import build_poe2scout_price_patch as poe2
import build_poe1_price_patch as poe1


@pytest.mark.parametrize('unit', ['e', 'c', 'd'])
@pytest.mark.parametrize('buy,sell', [(1000, 1100), (1000, 0), (0.1, 0.11), (0, 1100)])
def test_one_or_both_wrong_sides_cannot_bypass_history(unit, buy, sell):
    result = select_price(dict(currency_unit=unit, latest_buy1=buy, latest_sell1=sell,
                               buy_avg=10, sell_avg=11))
    assert result.price == Decimal(110).sqrt()
    assert 'history_fallback' in result.flags


def test_d_error_pair_is_checked_before_returning():
    result = select_price(dict(currency_unit='d', latest_buy1=100, latest_sell1=110,
                               buy_avg=1, sell_avg=1.1, error=True))
    assert result.price == Decimal('1.1').sqrt()
    assert {'buy_outlier', 'sell_outlier'} <= set(result.flags)


def test_duplicate_window_aliases_do_not_outvote_clean_previous_and_older_prices():
    result = select_price(dict(latest_buy1=1000, latest_sell1=0, prev_buy1=10,
                               buy_avg=1000, buy_avg_12h=1000,
                               buy_avg_yesterday=10, buy_avg_24h=10))
    assert result.price == 10
    assert 'buy_history_conflict' in result.flags


def test_normal_digit_boundary_is_not_an_ocr_rejection():
    result = select_price(dict(latest_buy1=10, latest_sell1=0, prev_buy1=9,
                               buy_avg=9.5, sell_avg=0.1, error=True,
                               error_info='价格出现剧烈波动, 可能为OCR识别故障'))
    assert result.price == 10
    assert 'history_fallback' not in result.flags


def test_realistic_price_move_uses_latest_quotes():
    result = select_price(dict(latest_buy1=20, latest_sell1=22, prev_buy1=19,
                               buy_avg=10, sell_avg=11, buy_avg_yesterday=10,
                               sell_avg_yesterday=11))
    assert result.price == Decimal(440).sqrt()
    assert 'history_fallback' not in result.flags


def test_low_liquidity_wide_book_does_not_force_lowball_quote():
    result = select_price(dict(latest_buy1=16, latest_sell1=0.2, prev_buy1=17,
                               buy_avg=19.1, sell_avg=0.29))
    assert result.price == 16
    assert 'wide_spread' in result.flags


def test_rejecting_a_buy_outlier_does_not_collapse_a_persistently_wide_book():
    result = select_price(dict(latest_buy1=3000, latest_sell1=0.2, prev_buy1=30,
                               buy_avg=30, sell_avg=0.2))
    assert result.price == 30
    assert 'history_fallback' in result.flags


def test_conflicting_divine_quotes_without_history_do_not_set_global_rate():
    result = select_price(dict(latest_buy1=3000, latest_sell1=300), divine=True)
    assert result.price == 0
    assert 'divine_rate_conflict' in result.flags


def test_decimal_repair_uses_the_supported_scale():
    result = select_price(dict(currency_unit='d', latest_buy1=2.33, latest_sell1=210,
                               prev_buy1=2.3, buy_avg=2.302, sell_avg=211.6))
    assert result.price == Decimal('4.893').sqrt()
    assert 'sell_decimal_shift' in result.flags


def test_decimal_repair_must_not_divide_legitimate_high_scale_by_100():
    result = select_price(dict(currency_unit='d', latest_buy1=2.6, latest_sell1=260,
                               prev_buy1=255, buy_avg=260, sell_avg=250))
    assert result.price == 260
    assert not any('decimal_shift' in flag for flag in result.flags)


def test_pair_alone_cannot_establish_a_decimal_repair():
    result = select_price(dict(currency_unit='d', latest_buy1=2.6, latest_sell1=260))
    assert not any('decimal_shift' in flag for flag in result.flags)
    assert 'wide_spread' in result.flags


@pytest.mark.parametrize('buy,sell', [(0, 3000), (3000, 3000), (30, 30)])
def test_divine_guard_covers_sell_only_and_both_sides(buy, sell):
    result = select_price(dict(latest_buy1=buy, latest_sell1=sell,
                               buy_avg=300, sell_avg=300), divine=True)
    assert result.price == 300


@pytest.mark.parametrize('bad', ['NaN', 'Infinity', '-Infinity', '1e1000000', '1e-1000000', True, -100, None])
def test_malformed_numbers_cannot_reach_arithmetic_or_prices(bad):
    result = select_price(dict(latest_buy1=bad, latest_sell1=bad, buy_avg=10, sell_avg=10))
    assert result.price == 10


def test_previous_quote_outside_latest_window_is_not_reused():
    result = select_price(dict(prev_buy1=1000, latest_datetime='2026-09-18 18:00:00',
                               prev_buy1_datetime='2026-09-15 18:00:00'))
    assert result.price == 0


def test_derived_e_value_cannot_bypass_domestic_price_or_divine_guard():
    prices, quality = poe2.collect_poecurrency_observations_with_quality([
        {'category_label':'currency', 'items':[
            dict(item_name='神圣石', currency_unit='e', latest_buy1=300,
                 buy_avg=300, e=30000),
            dict(item_name='sample', currency_unit='d', latest_buy1=2,
                 buy_avg=2, e=999999, error=True),
        ]}
    ])
    assert prices['divine'].price_exalted == 300
    assert prices['cn:sample'].price_exalted == 600
    assert 'explicit_price_rejected' in prices['cn:sample'].quality_flags
    assert quality['explicit_price_rejected_items'] >= 1


def test_poe1_uses_same_ocr_guard():
    value, _ = poe1._poecurrency_raw_price(dict(currency_unit='c', latest_buy1=1000,
                                             latest_sell1=1100, buy_avg=10, sell_avg=11))
    assert value == Decimal(110).sqrt()


def test_poe1_does_not_convert_with_an_international_divine_rate():
    items = [dict(item_name=f'item {i}', currency_unit='d', latest_buy1=2) for i in range(10)]
    with pytest.raises(ValueError, match='domestic'):
        poe1.collect_poecurrency_prices([{'category_label':'currency', 'items':items}], Decimal(300))
