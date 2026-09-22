"""Currency-independent display policy for paired tablet sample medians."""
from decimal import Decimal, ROUND_HALF_UP
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
    for places in range(2, 13):
        rounded = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        if rounded > 0:
            return format(rounded, 'f').rstrip('0').rstrip('.')
    raise ValueError('tablet price is too small to display')


def choose_currency(high, rates, counts):
    valid = [unit for unit in UNITS if rates.get(unit, 0) > 0]
    if not valid:
        raise ValueError('valid display exchange rates are required')
    # Tolerance applies only to floating-point conversion noise at the boundaries.
    readable = [unit for unit in valid if 1 - NOISE <= high / rates[unit] <= 100 + NOISE]
    majority = [unit for unit in readable if counts.get(unit, 0) > sum(counts.values()) / 2]
    if majority:
        return majority[0]
    if readable:
        return max(readable, key=lambda unit: (rates[unit], unit))
    def penalty(unit):
        amount = high / rates[unit]
        distance = -math.log(float(amount)) if amount < 1 else math.log(float(amount / 100))
        return distance, -rates[unit], unit
    return min(valid, key=penalty)


def format_pair(rare, magic, rates, anchors, counts=None):
    low, high = sorted((rare, magic))
    if low <= 0 or not low.is_finite() or not high.is_finite():
        raise ValueError('both tablet medians must be finite and positive')
    threshold = merge_threshold(high, anchors)
    merged = (high - low) / low <= threshold + NOISE
    unit = choose_currency(high, rates, counts or {})
    values = [(low + high) / 2] if merged else [low, high]
    labels = [display_number(value / rates[unit]) for value in values]
    if len(labels) == 2 and labels[0] == labels[1]:
        labels = labels[:1]
    return '~'.join(labels) + UNITS[unit], {
        'threshold': str(threshold), 'merged': merged, 'currency': unit,
        'low_anchor_divine': str(anchors[0]), 'high_anchor_divine': str(anchors[1]),
    }
