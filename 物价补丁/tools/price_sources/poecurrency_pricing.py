"""Robust pricing using only poecurrency's ordinary summary response.

The windows are correlated summaries, not independent trades. Group aliases,
compare each book side to its own history, and never vote across item names.
No token, history endpoint, external exchange rate, or network calls are used.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

ZERO = Decimal(0)
PAIR_RATIO = Decimal(5)
ITEM_RATIO = Decimal(3)
DIVINE_RATIO = Decimal(2)


def positive(value: Any) -> Decimal:
    """Bound arithmetic, not market value; reject malformed/overflowing OCR."""
    if value is None or isinstance(value, bool):
        return ZERO
    try:
        price = Decimal(str(value))
        return price if price.is_finite() and Decimal('1e-12') <= price <= Decimal('1e12') else ZERO
    except (InvalidOperation, TypeError, ValueError):
        return ZERO


def ratio(left: Decimal, right: Decimal) -> Decimal:
    return max(left, right) / min(left, right) if left > 0 and right > 0 else ZERO


def has_error(item: dict[str, Any]) -> bool:
    return str(item.get('error', '')).strip().lower() in {'true', '1', 'yes'} or bool(item.get('error_info'))


@dataclass(frozen=True)
class Decision:
    price: Decimal
    field: str
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Reference:
    price: Decimal = ZERO
    field: str = ''
    support: int = 0
    conflict: bool = False


def _first(item: dict[str, Any], fields: tuple[str, ...]) -> tuple[Decimal, str]:
    for field in fields:
        price = positive(item.get(field))
        if price:
            return price, field
    return ZERO, ''


def _recent_previous(item: dict[str, Any]) -> bool:
    latest, previous = item.get('latest_datetime'), item.get('prev_buy1_datetime')
    if not latest or not previous:
        return True
    try:
        gap = (datetime.fromisoformat(str(latest)) - datetime.fromisoformat(str(previous))).total_seconds()
        return 0 <= gap <= 86400
    except (TypeError, ValueError):
        return False


def _history(item: dict[str, Any], side: str, limit: Decimal) -> Reference:
    # One vote per window. A 12h alias must not count again as today's average,
    # nor a 24h alias as yesterday's average (the live API duplicates them).
    candidates = [
        _first(item, (f'{side}_avg_12h', f'{side}_avg')),
        _first(item, (f'{side}_avg_24h', f'{side}_avg_yesterday')),
    ]
    if side == 'buy' and _recent_previous(item):
        candidates.append(_first(item, ('prev_buy1',)))
    candidates = [(v, f) for v, f in candidates if v > 0]
    if not candidates:
        return Reference()
    # Select the largest mutually consistent cluster. Prefer the recent mean
    # on ties; an isolated previous OCR quote cannot outweigh two windows.
    ordered = sorted(candidates)
    clusters = [
        [entry for entry in ordered if low <= entry[0] <= low * limit]
        for low, _field in ordered
    ]
    cluster = max(clusters, key=lambda c: (len(c), *(int(entry in c) for entry in candidates)))
    values = [v for v, _f in cluster]
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 else (values[mid - 1] * values[mid]).sqrt()
    field = cluster[0][1] if len(cluster) == 1 else f'{side}_history_median'
    return Reference(median, field, len(cluster), len(cluster) < len(candidates))


def _combine(buy: Decimal, sell: Decimal, buy_field: str, sell_field: str, divine: bool) -> Decision:
    if buy and sell:
        if divine and ratio(buy, sell) > DIVINE_RATIO:
            return Decision(ZERO, '', ('divine_rate_conflict',))
        if ratio(buy, sell) > PAIR_RATIO:
            # A persistent wide book is not proof the cheaper side is correct.
            return Decision(buy, f'{buy_field}_wide_spread', ('wide_spread',))
        if divine:
            return Decision(buy, f'{buy_field}_divine_ratio')
        return Decision((buy * sell).sqrt(), f'geo_{buy_field}_{sell_field}')
    if buy:
        return Decision(buy, f'{buy_field}_only')
    if sell:
        return Decision(sell, f'{sell_field}_only')
    return Decision(ZERO, '')


def select_price(item: dict[str, Any], *, divine: bool = False) -> Decision:
    limit = DIVINE_RATIO if divine else ITEM_RATIO
    refs = {side: _history(item, side, limit) for side in ('buy', 'sell')}
    raw = {side: positive(item.get(f'latest_{side}1')) for side in refs}
    values = dict(raw)
    flags: list[str] = []
    error = has_error(item)
    # '9 -> 10' is an error on the source. Treat its flag as supporting evidence,
    # not as an order to replace a plausible current quote with stale averages.
    for side, ref in refs.items():
        if ref.conflict:
            flags.append(f'{side}_history_conflict')
        if values[side] and ref.price and ratio(values[side], ref.price) > limit:
            values[side] = ZERO
            flags.append(f'{side}_outlier')
        elif values[side] and error and not ref.price:
            values[side] = ZERO
            flags.append(f'{side}_unconfirmed_error')

    unit = str(item.get('currency_unit') or item.get('unit') or '').strip().lower()
    if not divine and unit in {'d', 'divine', 'divine orb', 'divine_orb', '神圣石', '神圣宝珠'}:
        for low_side, high_side in (('buy', 'sell'), ('sell', 'buy')):
            low, high = raw[low_side], raw[high_side]
            ref = refs[low_side]
            if not (low and low != low.to_integral_value()
                    and high > low and high == high.to_integral_value()):
                continue
            supported_low = bool(values[low_side] and ref.support >= 2)
            # Repeated missing decimals also contaminate arithmetic averages:
            # a mix of ~2D and ~200D becomes ~30D. Keep the established 100x
            # repair only when BOTH weak means sit strictly between the scales;
            # a historical cluster supporting the high scale vetoes it.
            mixed_means = all(
                r.support == 1 and low * ITEM_RATIO < r.price < high / ITEM_RATIO
                for r in refs.values()
            )
            if not (supported_low or mixed_means):
                continue
            repairs = [high / scale for scale in (Decimal(10), Decimal(100))
                       if ratio(high / scale, low) <= Decimal('1.5')
                       and (supported_low and ratio(high / scale, ref.price) <= Decimal('1.5')
                            or mixed_means and scale == 100)]
            if len(repairs) == 1:
                values[low_side] = low
                values[high_side] = repairs[0]
                flags.append(f'{high_side}_decimal_shift')
                if not supported_low:
                    flags.append('mixed_scale_history')

    # If only one side has history, its valid current quote can identify a
    # contradictory unanchored quote. This is evidence, not a min(price) rule.
    if values['buy'] and values['sell'] and ratio(values['buy'], values['sell']) > PAIR_RATIO:
        for side, other in (('buy', 'sell'), ('sell', 'buy')):
            if not refs[side].price and refs[other].price:
                values[side] = ZERO
                flags.append(f'{side}_unconfirmed_spread')
                break

    # On a persistently illiquid book, rejecting a bad buy quote must not make
    # the valuation collapse to a historical lowball sell order. Use the
    # supported buy history until its current quote becomes plausible again.
    if (not divine and raw['buy'] and not values['buy'] and values['sell']
            and refs['buy'].support >= 2
            and ratio(refs['buy'].price, refs['sell'].price) > PAIR_RATIO):
        flags.extend(('history_fallback', 'wide_spread'))
        return Decision(refs['buy'].price, f'{refs["buy"].field}_history_fallback',
                        tuple(dict.fromkeys(flags)))

    decision = _combine(values['buy'], values['sell'], 'latest_buy1', 'latest_sell1', divine)
    if not decision.price:
        flags.extend(decision.flags)
        # Use a historical estimate only when no validated current side remains.
        decision = _combine(refs['buy'].price, refs['sell'].price,
                            refs['buy'].field, refs['sell'].field, divine)
        if decision.price:
            decision = Decision(decision.price, f'{decision.field}_history_fallback', decision.flags)
            flags.append('history_fallback')
    if any('yesterday' in r.field or '24h' in r.field for r in refs.values()) and 'history_fallback' in flags:
        flags.append('older_history_used')
    return Decision(decision.price, decision.field, tuple(dict.fromkeys((*flags, *decision.flags))))
