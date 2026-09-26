"""Shared POE2 E/C/D display policy and paired tablet sample medians."""
from decimal import Decimal
from fractions import Fraction
import math

UNITS = {'exalted': 'E', 'chaos': 'C', 'divine': 'D'}
NOISE = Decimal('1e-9')


def percentile(values, fraction):
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * fraction
    index = int(position)
    return ordered[index] + (ordered[min(index + 1, len(ordered) - 1)] - ordered[index]) * (position - index)


def market_anchors(pairs):
    if not pairs or any(min(pair) <= 0 for pair in pairs):
        raise ValueError('valid paired medians are required for the market anchors')
    highs = [max(pair) for pair in pairs]
    low = percentile(highs, Decimal('.75'))
    high = max(percentile(highs, Decimal('.95')), 2 * low)
    return low, high


def merge_threshold(high, anchors):
    low_anchor, high_anchor = anchors
    if low_anchor <= 0 or high_anchor <= low_anchor:
        raise ValueError('invalid tablet market anchors')
    progress = min(1, max(0, math.log(float(high / low_anchor)) / math.log(float(high_anchor / low_anchor))))
    return Decimal('.2') - Decimal('.1') * Decimal(str(progress))


def display_number(value):
    value = Fraction(value)
    if value <= 0:
        raise ValueError('positive price required')
    places = 2
    truncated = value.numerator * 100 // value.denominator
    while not truncated:
        places += 1
        truncated = value.numerator * 10 ** places // value.denominator
    digits = str(truncated).zfill(places + 1)
    return (digits[:-places] + '.' + digits[-places:]).rstrip('0').rstrip('.')


def choose_currency(value, rates, counts=None):
    # Prices and rates use the same reference unit; Fraction avoids rounding
    # during conversion and makes exact boundaries independent of precision.
    valid = {unit: Fraction(rates[unit]) for unit in UNITS
             if rates.get(unit, 0) > 0}
    if not valid:
        raise ValueError('valid display exchange rates are required')
    if 'chaos' in valid and (
        'exalted' in valid and valid['chaos'] <= valid['exalted']
        or 'divine' in valid and valid['chaos'] >= valid['divine']
    ):
        del valid['chaos']
    eligible = [unit for unit in valid if Fraction(value) >= valid[unit]]
    return (max(eligible, key=lambda unit: (valid[unit], unit)) if eligible
            else min(valid, key=lambda unit: (valid[unit], unit)))


def format_value(value, rates):
    unit = choose_currency(value, rates)
    return display_number(Fraction(value) / Fraction(rates[unit])) + UNITS[unit]


def format_pair(rare, magic, rates, anchors, counts=None):
    low, high = sorted((rare, magic))
    if low <= 0 or not low.is_finite() or not high.is_finite():
        raise ValueError('both tablet medians must be finite and positive')
    threshold = merge_threshold(high, anchors)
    merged = (high - low) / low <= threshold + NOISE
    values = [(Fraction(low) + Fraction(high)) / 2] if merged else [low, high]
    unit = choose_currency(values[0], rates)
    labels = [display_number(Fraction(value) / Fraction(rates[unit])) for value in values]
    if len(labels) == 2 and labels[0] == labels[1]:
        labels = labels[:1]
    return '~'.join(labels) + UNITS[unit], {
        'threshold': str(threshold), 'merged': merged, 'currency': unit,
        'low_anchor_divine': str(anchors[0]), 'high_anchor_divine': str(anchors[1]),
    }
