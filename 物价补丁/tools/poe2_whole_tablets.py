"""CN whole-item tablet asking prices, isolated from modifier prices and FX."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlencode

from poe2_tablet_display import display_number, format_value, UNITS
from poe2_tablet_prices import TABLET_SLUGS, trade_query_scope

RARITIES = ('normal', 'magic', 'rare')
USE_STATS = {
    'Abyss_Tablet': '2369421690', 'Breach_Tablet': '2219129443',
    'Delirium_Tablet': '3879011313', 'Expedition_Tablet': '1714888636',
    'Irradiated_Tablet': '4041853756', 'Overseer_Tablet': '3376302538',
    'Ritual_Tablet': '3166002380', 'Temple_Tablet': '3035440454',
}


def positive(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result > 0 else Decimal(0)
    except (ValueError, InvalidOperation):
        return Decimal(0)


def validate_query(row, league):
    """Require the published whole-item scope, including remaining uses."""
    scope = trade_query_scope(row.get('trade_url'), row['rarity'], 'cn', league)
    if not scope:
        raise ValueError('whole-tablet trade market/rarity does not match')
    query = json.loads(scope)[1]
    unique = row['rarity'] == 'unique'
    if (set(query) != {'status', 'type', 'stats', 'filters', *(['name'] if unique else [])}
            or query.get('status') != {'option': 'securable'}
            or query.get('type') != row['base_name']
            or unique and query.get('name') != row['name']):
        raise ValueError('whole-tablet trade item identity does not match')
    # trade_query_scope removes only rarity.option, preserving all other filters.
    if query['filters'] != {
        'type_filters': {'filters': {'category': {'option': 'map.tablet'}, 'rarity': {}}},
        'trade_filters': {'filters': {'collapse': {'option': 'false'}}},
    }:
        raise ValueError('whole-tablet trade filters have changed')
    groups = query['stats']
    if not isinstance(groups, list) or len(groups) != 1:
        raise ValueError('whole-tablet trade use filter missing')
    group = groups[0]
    filters = group.get('filters', [])
    if (set(group) != {'type', 'filters'} or group.get('type') != 'and'
            or len(filters) != 1 or set(filters[0]) != {'id', 'value'}
            or filters[0].get('id') != 'implicit.stat_' + USE_STATS[row['base_id']]
            or filters[0]['value'] != {'min': 5 if unique else 10}):
        raise ValueError('whole-tablet trade use/affix conditions have changed')
    return scope


def select_quote(row):
    """Use the most-sampled supported native currency; never mix currency units."""
    samples = row.get('prices')
    if not isinstance(samples, dict):
        raise ValueError('invalid whole-tablet currency samples')
    candidates = []
    for unit, sample in samples.items():
        if unit not in UNITS:
            continue
        if not isinstance(sample, dict):
            raise ValueError('invalid whole-tablet currency sample')
        count = sample.get('count')
        if type(count) is not int or count <= 0:
            raise ValueError('invalid whole-tablet sample count')
        low, high = positive(sample.get('min')), positive(sample.get('max'))
        median = positive(sample.get('low_sample_median'))
        if low <= 0 or high < low or median and not low <= median <= high:
            raise ValueError('inconsistent whole-tablet price range')
        # Missing medians may fall back to an explicitly valid minimum.
        if sample.get('low_sample_median') is not None and not median:
            raise ValueError('invalid whole-tablet median')
        amount = median or low
        candidates.append((count, unit, amount, 'low_sample_median' if median else 'min'))
    if not candidates:
        return None
    count, unit, amount, statistic = max(candidates, key=lambda x: (x[0], x[1]))
    return {'price': display_number(amount) + UNITS[unit], 'amount': str(amount),
            'currency': unit, 'sample_count': count, 'statistic': statistic}


def select_base_reference(variants):
    """Use one name reference, preferring normal like international tablets."""
    if 'normal' in variants:
        rarity = 'normal'
        selection = 'normal'
    else:
        # The CN API quotes native currencies rather than normalized values.
        # Choose the most-sampled currency before comparing fallback prices.
        samples = {}
        for quote in variants.values():
            unit = quote['currency']
            samples[unit] = samples.get(unit, 0) + quote['sample_count']
        currency = max(samples, key=lambda unit: (samples[unit], unit))
        rarity = min((r for r in variants if variants[r]['currency'] == currency),
                     key=lambda r: (Decimal(variants[r]['amount']), r))
        selection = 'lowest_available_native_currency'
    return {**variants[rarity], 'variant': rarity.title(),
            'selection': selection, 'variants': variants}


def apply_whole_tablet_display(report, rates):
    """Keep selected native quotes, changing only their final display labels."""
    for quote in report.get('quotes', []):
        quote['native_price'] = display_number(Decimal(quote['amount'])) + UNITS[quote['currency']]
        rate = rates.get(quote['currency'], 0)
        quote['price'] = (format_value(Fraction(quote['amount']) * Fraction(rate), rates)
                          if rate > 0 else quote['native_price'])
        quote['display_converted'] = rate > 0
    for base in report.get('base_prices', {}).values():
        selected = base['variants'][base['variant'].lower()]
        base.update({key: selected[key] for key in ('price', 'native_price', 'display_converted')})
    report['display_rates_exalted'] = {key: str(value) for key, value in rates.items()}
    report['display_policy'] = 'E/C/D ladder, truncate without rounding'


def _fetch_snapshot(client, api_base, league, allow_stale):
    if not league or league == 'auto':
        raise ValueError('explicit CN whole-tablet league is required')
    offset = 0; revision = None; seen = set(); selected = []; skipped = []; pages = 0
    unique_catalog = {}
    while True:
        url = api_base.rstrip('/') + '/api/v1/whole-tablets/prices?' + urlencode({
            'server': 'cn', 'market': 'whole-tablet', 'league': league,
            'sort': 'name', 'limit': 200, 'offset': offset,
        })
        payload = client.get_json(url)
        if (not isinstance(payload, dict) or not isinstance(payload.get('data'), list)
                or payload.get('server') != 'cn' or payload.get('market') != 'whole-tablet'
                or payload.get('league') != league):
            raise ValueError('whole-tablet response market does not match selection')
        if type(payload.get('stale')) is not bool or payload['stale'] and not allow_stale:
            raise ValueError('whole-tablet freshness unavailable')
        snapshot = payload.get('snapshot') or {}
        collection = payload.get('collection') or {}
        current = (payload.get('total'), payload.get('updated_at'), snapshot.get('id'),
                   snapshot.get('generated_at'), collection.get('run_id'))
        if revision is not None and revision != current:
            raise ValueError('whole-tablet snapshot changed during pagination')
        revision = current
        total = payload.get('total')
        if (type(total) is not int or not 0 <= total <= 1000
                or payload.get('offset') != offset or not payload.get('updated_at')):
            raise ValueError('invalid whole-tablet pagination')
        pages += 1
        for row in payload['data']:
            if not isinstance(row, dict):
                raise ValueError('invalid whole-tablet row')
            identifier, base, rarity = (row.get(k) for k in ('id', 'base_id', 'rarity'))
            if not isinstance(identifier, str) or not identifier or identifier in seen:
                raise ValueError('duplicate or missing whole-tablet identity')
            seen.add(identifier)
            if base not in TABLET_SLUGS or rarity not in {*RARITIES, 'unique'}:
                skipped.append({'id': identifier, 'reason': 'unsupported item identity'})
                continue
            expected = row.get('name_en', '').replace(' ', '_') if rarity == 'unique' else base + ':' + rarity
            if (identifier != expected or not row.get('name') or not row.get('base_name')
                    or rarity != 'unique' and row.get('name_en', '').replace(' ', '_') != base):
                raise ValueError('inconsistent whole-tablet item identity')
            if rarity == 'unique':
                key = row['name_en'].casefold()
                if key in unique_catalog:
                    raise ValueError('ambiguous whole-tablet unique name')
                unique_catalog[key] = identifier
            if row.get('status') != 'priced':
                skipped.append({'id': identifier, 'reason': row.get('status') or 'missing status'})
                continue
            try:
                query = validate_query(row, league)
                price = select_quote(row)
                if type(row.get('sample_count')) is not int or row['sample_count'] <= 0:
                    raise ValueError('whole-tablet total sample count missing')
                if price and price['sample_count'] > row['sample_count']:
                    raise ValueError('whole-tablet sample count exceeds total')
                if not price:
                    raise ValueError('no supported native currency quote')
            except (ValueError, TypeError, KeyError) as exc:
                skipped.append({'id': identifier, 'reason': str(exc)})
                continue
            selected.append({**price, 'id': identifier, 'base_id': base, 'rarity': rarity,
                             'name': row['name'], 'name_en': row['name_en'],
                             'fetched_at': row.get('fetched_at'), 'searched_at': row.get('searched_at'),
                             'trade_url': row['trade_url'], 'query_scope': query})
        offset += len(payload['data'])
        if offset == total:
            break
        if not payload['data'] or offset > total or pages >= 10:
            raise ValueError('incomplete whole-tablet pagination')
    bases = {}; uniques = {}
    for row in selected:
        if row['rarity'] == 'unique':
            key = row['name_en'].casefold()
            if key in uniques:
                raise ValueError('ambiguous whole-tablet unique name')
            uniques[key] = row
        else:
            bases.setdefault(row['base_id'], {})[row['rarity']] = row
    base_prices = {base: select_base_reference(variants)
                   for base, variants in bases.items()}
    return {'status': 'partial' if skipped else 'ok', 'server': 'cn', 'market': 'whole-tablet',
            'league': league, 'url': url, 'total': total, 'pages': pages, 'rows': len(selected),
            'updated_at': payload['updated_at'], 'oldest_sample_at': payload.get('oldest_sample_at'),
            'stale': payload['stale'], 'snapshot': snapshot, 'collection': collection,
            'base_prices': base_prices, 'unique_prices': uniques, 'unique_catalog': unique_catalog,
            'quotes': selected, 'skipped': skipped,
            'price_policy': 'most_sampled_native_currency_median_then_minimum',
            'reference_note': '整件低价挂牌样本参考，非成交价；普/魔/稀至少10次，暗金至少5次；不筛词缀或腐化。'}


def fetch_cn_whole_tablets(client, api_base, league, *, cache_dir=None, allow_stale=True, on_retry=None):
    identity = {'schema': 1, 'api_base': api_base.rstrip('/'), 'server': 'cn',
                'market': 'whole-tablet', 'league': league}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    cache = Path(cache_dir) / ('whole-' + key + '.json') if cache_dir else None
    pages = {}
    class RecordingClient:
        def get_json(self, url):
            result = client.get_json(url)
            pages[url] = result
            return result
    try:
        # A collector can publish between pages. Retry the complete read once.
        for attempt in range(2):
            pages.clear()
            try:
                report = _fetch_snapshot(RecordingClient(), api_base, league, allow_stale)
                break
            except ValueError:
                if attempt:
                    raise
        if not report['quotes']:
            raise ValueError('no usable CN whole-tablet quotes')
    except Exception as live_error:
        if not cache or not cache.exists():
            raise
        saved = json.loads(cache.read_text(encoding='utf-8'))
        if saved.get('identity') != identity:
            raise ValueError('cached whole-tablet market does not match selection') from live_error
        class CachedClient:
            def get_json(self, url): return saved['pages'][url]
        report = _fetch_snapshot(CachedClient(), api_base, league, allow_stale)
        if not report['quotes']:
            raise ValueError('no usable cached whole-tablet quotes') from live_error
        report.update(source='cache', cache_saved_at=saved['saved_at'], live_error=str(live_error))
        if on_retry:
            on_retry(f"国服整件碑牌在线行情不可用，使用同赛季缓存（{saved['saved_at']}）")
        return report
    report['source'] = 'live'
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.whole-', dir=cache.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                json.dump({'identity': identity, 'saved_at': datetime.now(timezone.utc).isoformat(),
                           'pages': pages}, output, ensure_ascii=False)
            os.replace(name, cache)
        finally:
            Path(name).unlink(missing_ok=True)
    return report
