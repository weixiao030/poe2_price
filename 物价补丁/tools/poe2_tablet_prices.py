"""Optional tablet market layers. Generate validated resources before committing ZIP."""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections import Counter
import base64
import gzip
import hashlib
import io
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import html
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import urllib.parse
import zipfile

from poe2_name_price_patch import (
    apply_replacements_append, build_replacements, detect_base_item_layout,
    read_string_offset, scan_base_item_names,
)
from poe2_price_labels import format_unique_price_name, strip_existing_price
from poe2_tablet_refs import ORIGINAL, TYPES, canonical_reference, clean_references, validate_resources
from poe2_tablet_display import format_pair, market_anchors

TABLET_SLUGS = tuple(kind + "_Tablet" for kind in TYPES.values())
NINJA_URL = "https://poe.ninja/poe2/api/economy/stash/current/item/overview"
CHINESE = {"Traditional Chinese", "Simplified Chinese"}
LINE = re.compile(r'^(\s*)([#\d|+\-. ]+?)\s+"([^"\r\n]*)"([^\r\n]*)(\r?\n|$)$')
LANG = re.compile(r'^\s*lang\s+"([^"]+)"')
BLOCKS = re.compile(r'(?m)(?=^description[ \t]*\r?$)')
NUMBERS = re.compile(r'\{\d+(?::[^}]+)?\}|\(\d+-\d+\)|\b\d+\b')


def decimal(value) -> Decimal:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else Decimal(0)
    except (ValueError, InvalidOperation):
        return Decimal(0)


def format_price(value: Decimal, ratio: Decimal) -> str:
    if value <= 0 or ratio <= 0:
        return ""
    if value / ratio >= Decimal("0.1"):
        return f"{value / ratio:.2f}D"
    return f"{value:.1f}E" if value >= 10 else f"{value:.2f}E"


def _tablet_text_key(value) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r'\[([^\]|]+)(?:\|([^\]]+))?\]', lambda m: m[2] or m[1], text)
    text = re.sub(r'\{\d+(?::[^}]+)?\}', '__NUMBER__', text)
    text = re.sub(r'\(\d+(?:\.\d+)?-\d+(?:\.\d+)?\)|\b\d+(?:\.\d+)?\b', '__NUMBER__', text)
    # Singular game branches use "an additional" for the numeric value one.
    text = re.sub(r'\b(?:an|one) additional\b', '__NUMBER__ additional', text, flags=re.I)
    text = re.sub(r'\bthe first (?!__NUMBER__)', 'the first __NUMBER__ ', text, flags=re.I)
    text = re.sub(r'\bwill be a\b', 'will be', text, flags=re.I)
    text = re.sub(r'\bAbysses\b', 'Abyss', text, flags=re.I)
    text = re.sub(r'\bSentries\b', 'Sentry', text, flags=re.I)
    text = re.sub(r'\b(Strongbox|Boss)es\b', r'\1', text, flags=re.I)
    text = re.sub(r'\b(Monster|Modifier|Spirit|Essence|Shrine|Circle|Remnant|Hand|Chest|Exile|second|time|pack|Relic)s\b', r'\1', text, flags=re.I)
    return re.sub(r'\s+', ' ', text.replace('\\n', ' ')).strip().casefold()


@dataclass(frozen=True)
class Quote:
    text: str
    price: Decimal
    low: int | None = None
    high: int | None = None
    identifier: str = ""
    name: str = ""
    generation: str = ""
    stat: str = ""
    label: str = ""
    query_scope: str = ""
    sample_currencies: tuple = ()
    query_exact: bool | None = None
    query_context: str = ""
    query_reference: bool = False
    price_statistic: str = "median"


def trade_query_scope(url, rarity):
    """Compare the actual search, removing only the requested item rarity."""
    try:
        parsed = urllib.parse.urlparse(str(url))
        if parsed.hostname != 'www.pathofexile.com' or not parsed.path.startswith('/trade2/search/poe2/'):
            return ''
        token = parsed.path.rsplit('/', 1)[-1]
        if len(token) > 65536:
            return ''
        compressed = base64.urlsafe_b64decode(token + '=' * (-len(token) % 4))
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            return ''
        query = json.loads(raw)
        if query['filters']['type_filters']['filters']['rarity'].pop('option') != rarity:
            return ''
        # League and game context remain part of the comparison.
        return json.dumps([parsed.path.rsplit('/', 1)[0], query], sort_keys=True, separators=(',', ':'))
    except (ValueError, KeyError, TypeError, OSError, EOFError):
        return ''


def pair_tablet_quotes(quotes_by_rarity, api_reports):
    available = [rarity for rarity in ('magic', 'rare') if rarity in quotes_by_rarity
                 and api_reports[rarity].get('status', 'ok') == 'ok']
    if len(available) == 1:
        rarity = available[0]
        missing = 'rare' if rarity == 'magic' else 'magic'
        # Reuse the same single-value formatting policy without consuming the
        # failed snapshot. The report records only the source actually read.
        result, audit = pair_tablet_quotes(
            {side: quotes_by_rarity[rarity] for side in ('magic', 'rare')},
            {side: api_reports[rarity] for side in ('magic', 'rare')})
        for row in audit:
            if row['status'] == 'priced':
                row[missing + '_divine'] = None
                row['price_rarities'] = [rarity]
                row['price_statistics'] = {rarity: row['price_statistics'][rarity]}
                row['single_source_reason'] = missing + ' snapshot unavailable'
        return result, audit
    result = {}; audit = []; eligible = []
    rare_rate = decimal(api_reports['rare']['rates'].get('exalted'))
    magic_rate = decimal(api_reports['magic']['rates'].get('exalted'))
    if rare_rate <= 0 or magic_rate <= 0:
        raise ValueError('tablet exchange rates are missing')
    # Convert each snapshot with its own rates, then display all prices using
    # one common revision. This also supports a cached side during an outage.
    rates = {k: decimal(v) for k, v in api_reports['rare']['rates'].items()}
    if api_reports['rare'].get('source') == 'cache' and api_reports['magic'].get('source') != 'cache':
        rates = {k: decimal(v) for k, v in api_reports['magic']['rates'].items()}
    rates['divine'] = Decimal(1)
    for slug in TABLET_SLUGS:
        rare = {q.identifier:q for q in quotes_by_rarity['rare'].get(slug, [])}
        magic = {q.identifier:q for q in quotes_by_rarity['magic'].get(slug, [])}
        for identifier in sorted(rare.keys() | magic.keys()):
            rare_q, magic_q = rare.get(identifier), magic.get(identifier)
            q, other = rare_q or magic_q, magic_q or rare_q
            if not identifier or (q.text, q.name, q.generation, q.low, q.high) != (other.text, other.name, other.generation, other.low, other.high):
                audit.append({'tablet':slug, 'id':identifier, 'text':q.text, 'status':'excluded',
                              'reason':'magic/rare modifier identity differs'})
                continue
            rare_d = rare_q.price * rare_rate if rare_q else None
            magic_d = magic_q.price * magic_rate if magic_q else None
            exact = (q.query_exact, other.query_exact)
            single = 'magic' if rare_q is None else 'rare' if magic_q is None else None
            single_reason = 'other rarity has no usable quote' if single else ''
            reference = (q.query_reference and other.query_reference
                         and q.query_scope == other.query_scope)
            if (exact in ((True, False), (False, True)) and q.query_context
                    and q.query_context == other.query_context):
                single = 'rare' if q.query_exact else 'magic'
                single_reason = 'other query also matches a different available game modifier'
            elif (not q.query_scope or q.query_scope != other.query_scope
                    or False in exact and not reference):
                audit.append({'tablet':slug, 'id':identifier, 'text':q.text, 'status':'excluded',
                              'reason':('trade query includes a different available game modifier'
                                        if False in exact else 'trade query scope is missing or differs between rarities')})
                continue
            eligible.append((slug, q, other, rare_d, magic_d, single, reference, single_reason))
    if not eligible:
        raise ValueError('no tablet pairs have matching trade query scopes or identities')
    values = lambda r, m, single: (r, r) if single == 'rare' else (m, m) if single == 'magic' else (r, m)
    anchors = market_anchors([values(row[3], row[4], row[5]) for row in eligible])
    for slug, q, other, rare_d, magic_d, single, reference, single_reason in eligible:
        counts = Counter()
        if single != 'magic': counts.update(dict(q.sample_currencies))
        if single != 'rare': counts.update(dict(other.sample_currencies))
        label, policy = format_pair(*values(rare_d, magic_d, single), rates, anchors, counts)
        result.setdefault(slug, []).append(replace(q, label=label))
        audit.append({'tablet':slug, 'id':q.identifier, 'text':q.text, 'name':q.name,
                      'generation':q.generation, 'rare_divine':str(rare_d) if rare_d is not None else None,
                      'magic_divine':str(magic_d) if magic_d is not None else None, 'label':label, 'status':'priced',
                      'price_rarities':[single] if single else ['magic', 'rare'],
                      'price_statistics':{r: quote.price_statistic for r, quote in [('rare',q),('magic',other)]
                                          if not single or r == single},
                      'single_source_reason':single_reason,
                      'query_scope_warning':('website reference price; query can also match a different game modifier'
                                             if reference else ''),
                      'display_mode':'range' if '~' in label else 'single', 'policy':policy})
    return result, audit


def quote_for_record(quote, text):
    """Resolve the variable against the game's placeholder; keep constants exact."""
    if _tablet_text_key(quote.text) != _tablet_text_key(text):
        return None
    quoted = NUMBERS.findall(quote.text)
    if len(quoted) <= 1:
        return quote  # Includes the game's singular, written-out number branches.
    plain = re.sub(r'\[([^\]|]+)(?:\|([^\]]+))?\]', lambda m: m[2] or m[1], text)
    template = NUMBERS.findall(plain)
    if len(template) != len(quoted) or template.count('{0}') != 1:
        return None
    bounds = None
    for token, value in zip(template, quoted):
        if token == '{0}':
            parts = value.strip('()').split('-')
            if not all(part.isdigit() for part in parts):
                return None
            bounds = (int(parts[0]), int(parts[-1]))
        elif token != value:
            return None
    return replace(quote, low=bounds[0], high=bounds[1]) if bounds else None


def _tablet_price_from_row(row, rates=None) -> Decimal:
    return _tablet_price_details(row, rates)[0]


def _tablet_price_details(row, rates=None):
    converted = row.get("converted") or {}
    fallback = (Decimal(0), '')
    if str(converted.get("currency", "")).lower() in {"exalted", "exalted orb"}:
        # An incomplete conversion must not silently turn a subset into the total.
        if converted.get("missing_count", 0):
            return Decimal(0), ''
        for key in ("median", "low_sample_median"):
            if decimal(converted.get(key)) > 0:
                return decimal(converted[key]), key
        if decimal(converted.get('min')) > 0:
            fallback = (decimal(converted['min']), 'min')
    rates = rates or {}
    groups = row.get("prices") or {}
    values = []; medians = []
    for unit, sample in groups.items():
        if not isinstance(sample, dict):
            return fallback
        factor = Decimal(1)
        if unit != "exalted":
            if decimal(rates.get("exalted")) <= 0 or decimal(rates.get(unit)) <= 0:
                return fallback
            factor = decimal(rates[unit]) / decimal(rates["exalted"])
        for key in ('median', 'low_sample_median'):
            if decimal(sample.get(key)) > 0:
                medians.append((decimal(sample[key]) * factor, key))
                break
        values.append(decimal(sample.get('min')) * factor)
    # Currency-group medians cannot reconstruct a combined median. Their
    # minima can reconstruct the minimum when every group is convertible.
    if len(groups) == 1 and medians:
        return medians[0]
    if fallback[0] > 0:
        return fallback
    if values and all(v > 0 for v in values):
        return min(values), 'min'
    return Decimal(0), ''


class TabletSnapshotError(ValueError):
    """A successful response contains an unavailable or inconsistent snapshot."""


def fetch_tablet_affix_prices(client, api_base, league, rarity="rare", allow_stale=False,
                             allow_stale_snapshot=False, snapshot_retries=0, on_retry=None,
                             cache_dir=None):
    identity = {'api_base':api_base.rstrip('/'), 'league':league, 'rarity':rarity}
    cache_key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    cache_path = Path(cache_dir) / (cache_key + '.json') if cache_dir else None
    pages = {}
    class RecordingClient:
        def get_json(self, url):
            result = client.get_json(url)
            pages[url] = result
            return result
    try:
        prices, report = _fetch_tablet_with_retry(RecordingClient(), api_base, league, rarity,
            allow_stale, allow_stale_snapshot, snapshot_retries, on_retry)
        if not prices and cache_path and cache_path.exists():
            raise TabletSnapshotError('tablet snapshot contains no usable prices')
    except Exception as live_error:
        if cache_path is None or not cache_path.exists():
            raise
        try:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
            if cached.get('schema') != 1 or cached.get('identity') != identity:
                raise ValueError('cached tablet market does not match selection')
            class CachedClient:
                def get_json(self, url): return cached['pages'][url]
            prices, report = _fetch_tablet_affix_snapshot(CachedClient(), api_base, league, rarity,
                allow_stale, allow_stale_snapshot)
            if not prices:
                raise ValueError('cached tablet snapshot contains no usable prices')
        except Exception as cache_error:
            raise ValueError(f'{live_error}; cached snapshot rejected: {cache_error}') from live_error
        report.update(source='cache', cache_saved_at=cached['saved_at'],
            live_error=f'{type(live_error).__name__}: {live_error}',
            snapshot_attempts=getattr(live_error, 'snapshot_attempts', 1),
            snapshot_retry_reasons=getattr(live_error, 'snapshot_retry_reasons', []),
            freshness='last_successful_snapshot')
        if on_retry:
            name = '魔法' if rarity == 'magic' else '稀有'
            on_retry(f"碑牌{name}在线行情不可用，使用同赛季本地缓存（保存于 {cached['saved_at']}）：{live_error}")
        return prices, report
    report['source'] = 'live'
    if cache_path and prices:
        temporary = None
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.tablet-', suffix='.json', dir=cache_path.parent)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump({'schema':1, 'identity':identity, 'saved_at':datetime.now(timezone.utc).isoformat(),
                           'pages':pages}, stream, ensure_ascii=False)
            os.replace(temporary, cache_path)
        except OSError as exc:
            report['cache_write_error'] = str(exc)
        finally:
            if temporary: Path(temporary).unlink(missing_ok=True)
    return prices, report


def _fetch_tablet_with_retry(client, api_base, league, rarity, allow_stale,
                            allow_stale_snapshot, snapshot_retries, on_retry):
    # HTTP failures already have a deadline and retries in the transport client.
    # Restart pagination only for transient snapshot failures, never mix pages.
    import time
    reasons = []
    for attempt in range(max(0, min(2, snapshot_retries)) + 1):
        try:
            prices, report = _fetch_tablet_affix_snapshot(
                client, api_base, league, rarity, allow_stale, allow_stale_snapshot)
            if not prices and snapshot_retries:
                raise TabletSnapshotError('tablet snapshot contains no usable prices')
            report.update(snapshot_attempts=attempt + 1, snapshot_retry_reasons=reasons)
            return prices, report
        except TabletSnapshotError as exc:
            reasons.append(str(exc))
            exc.snapshot_attempts = attempt + 1
            exc.snapshot_retry_reasons = list(reasons)
            if attempt >= max(0, min(2, snapshot_retries)):
                raise
            if on_retry:
                name = '魔法' if rarity == 'magic' else '稀有'
                on_retry(f'碑牌{name}快照暂不可用，{attempt + 1} 秒后从第一页重试（第 {attempt + 2} 次）：{exc}')
            time.sleep(attempt + 1)


def _fetch_tablet_affix_snapshot(client, api_base, league, rarity, allow_stale,
                               allow_stale_snapshot):
    if not league:
        raise ValueError("tablet league is required")
    if rarity not in {"magic", "rare"}:
        raise ValueError("tablet rarity must be magic or rare")
    result = {}; offset = 0; snapshot = None; total = None; seen = set(); pages = 0; rates = {}
    while True:
        query = urllib.parse.urlencode(dict(
            server="international", category="tablet", rarity=rarity,
            league=league, display_currency="exalted", sort="name",
            limit=200, offset=offset,
        ))
        payload = client.get_json(api_base.rstrip('/') + '/api/v1/prices?' + query)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise TabletSnapshotError("invalid tablet prices response")
        state = payload.get("snapshot") or {}
        exchange = payload.get("exchange_rates") or {}
        if (state.get("league") != league or exchange.get("league") != league):
            raise ValueError("tablet API league does not match selection")
        config = state.get("config") or {}
        if payload.get("rarity") is None and config.get("rarity") is None:
            raise ValueError("tablet API response does not identify its rarity")
        if (payload.get("server") is not None and payload.get("server") != "international"
                or payload.get("category") is not None and payload.get("category") != "tablet"
                or payload.get("rarity") is not None and payload.get("rarity") != rarity
                or config.get("rarity") is not None and config.get("rarity") != rarity):
            raise ValueError("tablet API snapshot rarity does not match selection")
        snapshot_usable = (state.get("stale") is False
                           or allow_stale_snapshot and state.get("stale") is True)
        if (not snapshot_usable or exchange.get("stale") is not False) and not allow_stale:
            raise TabletSnapshotError("tablet API snapshot or exchange rates are stale")
        if not state.get("id") or snapshot and state["id"] != snapshot:
            raise TabletSnapshotError("tablet snapshot changed during pagination")
        if total is not None and payload.get("total") != total:
            raise TabletSnapshotError("tablet pagination total changed")
        snapshot = state["id"]; total = int(payload.get("total", 0)); pages += 1
        if total <= 0 or total > 12000 or int(payload.get("offset", -1)) != offset:
            raise TabletSnapshotError("invalid tablet pagination")
        current_rates = {k: decimal(v) for k, v in exchange.get("values", {}).items()}
        current_rates["divine"] = Decimal(1)
        if rates and rates != current_rates:
            raise TabletSnapshotError("tablet exchange rates changed during pagination")
        rates = current_rates
        for row in payload["data"]:
            if any(row.get(k) is not None and row[k] != v for k, v in
                   (('server','international'), ('category','tablet'), ('rarity',rarity))):
                raise ValueError('tablet row market does not match the requested rarity')
            identifier = row.get("id")
            if not identifier or identifier in seen:
                raise TabletSnapshotError("tablet pagination contains missing or duplicate IDs")
            seen.add(identifier)
            slug = row.get("tablet")
            if slug not in TABLET_SLUGS or row.get("status") != "ok" or int(row.get("sample_count", 0)) <= 0:
                continue
            text = str(row.get("text_en") or "")
            value, statistic = _tablet_price_details(row, rates)
            if not text or value <= 0:
                continue
            numbers = re.findall(r'\((\d+)-(\d+)\)|(\b\d+\b)', text)
            bounds = [(int(a or c), int(b or c)) for a, b, c in numbers]
            # More numbers can be literal caps, not additional stats. The game
            # template resolves them before pricing; never discard the quote.
            ranges = [(int(a), int(b)) for a, b, c in numbers if a]
            low, high = ranges[0] if len(ranges) == 1 else bounds[0] if len(bounds) == 1 else (None, None)
            result.setdefault(slug, []).append(Quote(text, value, low, high,
                identifier=identifier, name=str(row.get('name_en') or ''),
                generation=str(row.get('generation') or ''),
                price_statistic=statistic,
                query_scope=trade_query_scope(row.get('trade_url'), rarity),
                sample_currencies=tuple((unit, int(sample.get('count', 0)))
                    for unit, sample in (row.get('prices') or {}).items()
                    if isinstance(sample, dict) and isinstance(sample.get('count', 0), int) and sample.get('count', 0) > 0)))
        size = len(payload["data"]); offset += size
        if offset == total:
            break
        if not size or offset > total or pages >= 60:
            raise TabletSnapshotError("incomplete tablet snapshot")
    return result, {"league": league, "rarity": rarity, "snapshot": snapshot, "pages": pages, "total": total,
                    "rows": sum(map(len, result.values())), "rates": {k: str(v) for k, v in rates.items()},
                    "query_config": state.get("config", {}),
                    "published_at": state.get("published_at"),
                    "oldest_sample_at": state.get("oldest_sample_at"),
                    "snapshot_stale": state.get("stale"),
                    "exchange_rates_stale": exchange.get("stale"),
                    "allow_stale_snapshot": bool(allow_stale_snapshot),
                    "allow_stale": bool(allow_stale), "price_statistic":"median_then_minimum",
                    "minimum_price_fallback":True,
                    "minimum_price_ids":[q.identifier for quotes in result.values() for q in quotes if q.price_statistic == 'min']}


def fetch_poe_ninja_precursor_tablets(client, league, api_url=NINJA_URL):
    if not league:
        raise ValueError("poe.ninja league is required")
    url = api_url + '?' + urllib.parse.urlencode(dict(league=league, type="PrecursorTablets"))
    payload = client.get_json(url)
    if not isinstance(payload, dict) or not isinstance(payload.get("lines"), list):
        raise ValueError("invalid poe.ninja PrecursorTablets response")
    core = payload.get("core") or {}; ratio = decimal((core.get("rates") or {}).get("exalted"))
    if core.get("primary") != "divine" or ratio <= 0:
        raise ValueError("invalid poe.ninja tablet currency unit")
    prices = {}; values = {}
    for row in payload["lines"]:
        slug = str(row.get("baseType") or row.get("name") or "").replace(' ', '_')
        variant = row.get("variant")
        if slug not in TABLET_SLUGS or variant not in {"Normal", "Magic", "Rare"} or row.get("corrupted") is not False:
            continue
        if decimal(row.get("listingCount")) <= 0 or decimal(row.get("primaryValue")) <= 0:
            continue
        price = format_price(decimal(row["primaryValue"]) * ratio, ratio)
        if variant in prices.setdefault(slug, {}) and prices[slug][variant] != price:
            raise ValueError("ambiguous poe.ninja tablet variant")
        prices[slug][variant] = price
        values.setdefault(slug, {})[variant] = decimal(row['primaryValue'])
    if not prices:
        raise ValueError("no usable poe.ninja tablet prices")
    base_prices = {}
    for slug, variants in values.items():
        variant = 'Normal' if 'Normal' in variants else min(variants, key=lambda v:(variants[v], v))
        base_prices[slug] = {'price':prices[slug][variant], 'variant':variant,
                             'selection':'normal' if variant == 'Normal' else 'lowest_available'}
    return {"status": "ok", "url": url, "lines": len(payload["lines"]),
            "usable_lines": sum(map(len, prices.values())), "divine_exalted": str(ratio), "prices": prices,
            "base_prices":base_prices}


def decode_resource(raw: bytes):
    if raw.startswith(b'\xff\xfe'):
        return raw[2:].decode('utf-16-le'), 'utf-16-le', b'\xff\xfe'
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw[3:].decode('utf-8'), 'utf-8', b'\xef\xbb\xbf'
    return raw.decode('utf-8'), 'utf-8', b''


def condition_bounds(condition):
    parts = condition.strip().split('|')
    if len(parts) == 1:
        return (None, None) if parts[0] == '#' else (int(parts[0]), int(parts[0]))
    if len(parts) == 2:
        return tuple(None if value == '#' else int(value) for value in parts)
    raise ValueError("unsupported CSD condition")


def clean_chinese_markup(text):
    """Drop unpaired closing link brackets, retaining every balanced game link."""
    output = []
    language = ''
    for line in text.splitlines(keepends=True):
        if line.startswith('description'):
            language = ''
        lang = LANG.match(line)
        if lang:
            language = lang[1]
        record = LINE.match(line)
        if language in CHINESE and record:
            content = []
            depth = 0
            for char in record[3]:
                if char == '[':
                    depth += 1
                elif char == ']':
                    if depth == 0:
                        continue
                    depth -= 1
                content.append(char)
            line = f'{record[1]}{record[2]} "{"".join(content)}"{record[4]}{record[5]}'
        output.append(line)
    return ''.join(output)


def price_tablet_names(data, base_prices):
    """Reuse unique markup for each base's explicitly selected market quote."""
    rows = []
    priced = []
    entries = scan_base_item_names(data)
    for entry in entries:
        for base, kind in TYPES.items():
            if entry.metadata_path != f'Metadata/Items/TowerAugment/{base}Augment':
                continue
            selected = base_prices.get(kind + '_Tablet', {})
            price = selected.get('price', '')
            name = strip_existing_price(entry.name)
            rows.append({'metadata_path':entry.metadata_path,
                         'new_name':format_unique_price_name(name, price, 'markup') if price else name})
            if price:
                priced.append({'tablet':kind + '_Tablet', **selected})
    replacements, warnings = build_replacements(entries, rows, '=', False, 'append', False)
    if warnings:
        raise ValueError('tablet base name mapping failed: ' + '; '.join(warnings))
    return apply_replacements_append(data, replacements), priced


def price_block(block, quotes, ratio):
    lines = block.splitlines(keepends=True)
    if len(lines) < 3 or not re.match(r'^\s*1\s+\S+\s*$', lines[1]):
        return block, set(), 0
    stat = lines[1].split()[1]
    quotes = [q for q in quotes if not q.stat or q.stat == stat]
    boundaries = [0] + [i for i, line in enumerate(lines) if LANG.match(line)] + [len(lines)]
    sections = [lines[boundaries[i]:boundaries[i+1]] for i in range(len(boundaries)-1)]
    # Some current game blocks ship only one Chinese translation. Use that
    # official text for the missing Chinese locale instead of losing the price.
    languages = {LANG.match(section[0])[1]:section for section in sections[1:]}
    for language in sorted(CHINESE - languages.keys()):
        fallback = next((languages[name][1:] for name in sorted(CHINESE) if name in languages), None)
        if fallback is not None:
            newline = '\r\n' if '\r\n' in block else '\n'
            sections.append([f'\tlang "{language}"{newline}', *fallback])
    english = [LINE.match(line) for line in sections[0] if LINE.match(line)]
    matches = {}
    for i, record in enumerate(english):
        compatible = [matched for quote in quotes if (matched := quote_for_record(quote, record[3])) is not None]
        # Some game translations use identical increased text for both signs.
        # Prefer the non-negated branch when the same text exists on both.
        if 'negate' in record[4] and any('negate' not in r[4] and _tablet_text_key(r[3]) == _tablet_text_key(record[3]) for r in english):
            compatible = []
        if compatible:
            matches[i] = compatible
    if not matches:
        return block, set(), 0
    used = set(); changes = 0
    for section_index, section in enumerate(sections[1:], 1):
        language = LANG.match(section[0])[1]
        if language not in CHINESE:
            continue
        record_positions = [i for i, line in enumerate(section) if LINE.match(line)]
        if len(record_positions) != len(english):
            # Refuse to pair translations by guesswork when branch counts differ.
            continue
        for branch in reversed(range(len(record_positions))):
            if branch not in matches:
                continue
            position = record_positions[branch]; record = LINE.match(section[position])
            try:
                lower, upper = condition_bounds(record[2])
            except ValueError:
                continue
            factor = 100 if 'divide_by_one_hundred 1' in record[4] else 1
            other = re.sub(r'\s*divide_by_one_hundred\s+1', '', record[4]).strip()
            other = re.sub(r'\bcanonical_line\b', '', other).strip()
            if 'negate 1' in other:
                factor *= -1
                other = other.replace('negate 1', '').strip()
            if other:
                continue  # unknown numeric transformation must not be guessed
            candidates = []
            for quote in matches[branch]:
                low = quote.low * factor if quote.low is not None else lower
                high = quote.high * factor if quote.high is not None else upper
                if factor < 0 and low is not None and high is not None: low, high = high, low
                if lower is not None: low = max(low, lower) if low is not None else lower
                if upper is not None: high = min(high, upper) if high is not None else upper
                if low is not None and high is not None and low > high:
                    continue
                candidates.append((low, high, quote))
            # Conflicting quotes for the same Stat/value cannot be combined by
            # choosing a minimum: that would silently replace its median.
            def unique_quote(applicable):
                if len({q.label or str(q.price) for q in applicable}) != 1:
                    raise ValueError(f'ambiguous tablet prices for {stat}')
                return applicable[0]
            cuts = sorted({n for low, high, _ in candidates for n in (low, high + 1 if high is not None else None) if n is not None})
            ranges = []
            if candidates and all(low is None and high is None for low, high, _ in candidates):
                ranges = [(None, None, unique_quote([q for _, _, q in candidates]))]
            else:
                for low, end in zip(cuts, cuts[1:]):
                    applicable = [q for lo, hi, q in candidates if (lo is None or lo <= low) and (hi is None or end - 1 <= hi)]
                    if applicable: ranges.append((low, end - 1, unique_quote(applicable)))
            additions = []
            for low, high, quote in ranges:
                condition = '#' if low is None and high is None else str(low) if low == high else f"{low if low is not None else '#'}|{high if high is not None else '#'}"
                price = quote.label or format_price(quote.price, ratio)
                if not price: continue
                additions.append(f'{record[1]}{condition} "{record[3]}={price}"{record[4]}{record[5]}')
                # Coverage is recorded only after the matching price is emitted.
                used.update(q.identifier or q.text for lo, hi, q in candidates
                            if (hi is None or low is None or hi >= low)
                            and (lo is None or high is None or lo <= high))
                changes += 1
            # Keep the untouched fallback for values not covered by market data.
            section[position:position] = additions
        count_position = next((i for i, line in enumerate(section[1:], 1) if re.fullmatch(r'\s*\d+\s*', line)), None)
        if count_position is not None:
            newline = '\r\n' if section[count_position].endswith('\r\n') else '\n'
            section[count_position] = f'\t{sum(bool(LINE.match(line)) for line in section)}{newline}'
        sections[section_index] = section
    return ''.join(''.join(section) for section in sections), used, changes


def validate_csd(text):
    if any(ord(char) < 32 and char not in '\r\n\t' for char in text):
        raise ValueError("CSD contains control characters")
    for block in BLOCKS.split(text):
        if not block.startswith('description'):
            continue
        lines = block.splitlines(keepends=True)
        boundaries = [0] + [i for i, line in enumerate(lines) if LANG.match(line)] + [len(lines)]
        for i in range(len(boundaries)-1):
            section = lines[boundaries[i]:boundaries[i+1]]
            start = 2 if i == 0 else 1
            count = next((int(line.strip()) for line in section[start:] if line.strip().isdigit()), None)
            records = sum(bool(LINE.match(line)) for line in section)
            if count is None or count != records:
                raise ValueError(f"CSD language record count mismatch: {lines[1].strip()}, section {i}, {count} != {records}")


def _append_tablet_price_to_csd(source, priced_mods, divine_exalted):
    text, encoding, bom = decode_resource(Path(source).read_bytes())
    if isinstance(priced_mods, dict):
        priced_mods = [Quote(key, value) for key, value in priced_mods.items()]
    changed = 0; matched = 0; output = []
    for block in BLOCKS.split(text):
        modified, used, count = price_block(block, priced_mods, divine_exalted)
        output.append(modified); changed += count; matched += bool(used)
    text = clean_chinese_markup(''.join(output)); validate_csd(text)
    return bom + text.encode(encoding), matched, changed


def _redirect_tablet_base_items(data, tablet_types):
    layout = detect_base_item_layout(data); output = bytearray(data); count = 0
    for row in range(layout.row_count):
        at = 4 + row * layout.row_size
        metadata = read_string_offset(data, layout, struct.unpack_from('<I', data, at)[0])[0]
        for base, kind in TYPES.items():
            if kind not in tablet_types or metadata != f'Metadata/Items/TowerAugment/{base}Augment': continue
            current = read_string_offset(data, layout, struct.unpack_from('<Q', data, at + 40)[0])[0]
            if canonical_reference(metadata, current) != ORIGINAL:
                raise ValueError('tablet inheritance already modified by another patch')
            pointer = len(output) - layout.string_base
            output.extend((f'Metadata/Items/TowerAugments/Poe2Price/{kind}\0').encode('utf-16-le'))
            struct.pack_into('<Q', output, at + 40, pointer); count += 1
    return bytes(output), count


def build_tablet_affix_resources(*, client, api_base, league, template_it, template_csd,
                                source_baseitems, patched_baseitems, output_zip, game_path, resource_report,
                                english_baseitems=None, template_map_csd=None, template_global_csd=None,
                                allow_stale=False, tablet_mods=None, tablet_stats=None, tablet_tags=None,
                                on_retry=None, cache_dir=None):
    reports = {}; quotes_by_rarity = {}; ninja = {}
    api_reports = {}
    for rarity in ("magic", "rare"):
        try:
            quotes_by_rarity[rarity], api_reports[rarity] = fetch_tablet_affix_prices(
                client, api_base, league, rarity=rarity, allow_stale=allow_stale,
                allow_stale_snapshot=rarity == "magic", snapshot_retries=2, on_retry=on_retry,
                cache_dir=cache_dir)
            api_reports[rarity]['status'] = 'ok'
        except Exception as exc:
            api_reports[rarity] = {'status':'unavailable', 'rarity':rarity,
                                   'reason':f'{type(exc).__name__}: {exc}',
                                   'snapshot_attempts':getattr(exc, 'snapshot_attempts', 1),
                                   'snapshot_retry_reasons':getattr(exc, 'snapshot_retry_reasons', [])}
    # Keep the two snapshots independent, including their failure states.
    has_quotes = any(quotes_by_rarity.values())
    api_ok = [api_reports[r].get('status') == 'ok' for r in ("magic", "rare")]
    reports['api'] = {
        'rarities': api_reports,
        # Retain the existing top-level conversion fields for callers that
        # only need a common Divine ratio.
        **next((r for r in api_reports.values() if r.get('status') == 'ok'), {}),
        'status': 'ok' if all(api_ok) else ('partial' if any(api_ok) else 'unavailable'),
    }
    try:
        ninja = fetch_poe_ninja_precursor_tablets(client, league)
        reports['poe_ninja_precursor_tablets'] = ninja
    except Exception as exc:
        reports['poe_ninja_precursor_tablets'] = {'status':'unavailable', 'reason':f'{type(exc).__name__}: {exc}'}
    rates = reports['api'].get('rates', {})
    ratio = 1 / decimal(rates['exalted']) if decimal(rates.get('exalted')) > 0 else decimal(ninja.get('divine_exalted'))
    if ratio <= 0 or not has_quotes and not ninja.get('prices'):
        raise ValueError('tablet price sources unavailable; ' + json.dumps(reports, ensure_ascii=False))
    templates_ready = bool(template_it and template_it.exists() and template_csd and template_csd.exists())
    quotes = {}; pair_audit = []; mapping = []
    if has_quotes and templates_ready:
        if not all(path and Path(path).exists() for path in (tablet_mods, tablet_stats, tablet_tags)):
            raise ValueError('current game Mods/Stats/Tags are required to bind tablet prices')
        from poe2_tablet_catalog import bind_game_stats, game_affix_catalog, report_game_coverage
        catalog = game_affix_catalog(mods_path=tablet_mods, stats_path=tablet_stats,
            tags_path=tablet_tags, baseitems_path=english_baseitems or source_baseitems)
        quoted_mapping = []
        for rarity in quotes_by_rarity:
            quotes_by_rarity[rarity], rarity_mapping = bind_game_stats(quotes_by_rarity[rarity], game_catalog=catalog)
            quoted_mapping.extend(rarity_mapping)
        reports['game_coverage'] = report_game_coverage(catalog, quoted_mapping)
        quotes, pair_audit = pair_tablet_quotes(quotes_by_rarity, api_reports)
        excluded = [row for row in pair_audit if row['status'] == 'excluded']
        reports['quote_validation'] = {'status':'partial' if excluded else 'ok', 'excluded':excluded,
            'minimum_price': [row['id'] for row in pair_audit if 'min' in row.get('price_statistics', {}).values()],
            'single_source': [row['id'] for row in pair_audit if row.get('single_source_reason')],
            'reference_quotes': [row['id'] for row in pair_audit if row.get('query_scope_warning')]}
        quotes, mapping = bind_game_stats(quotes, game_catalog=catalog)
    elif has_quotes:
        reports['affix_templates'] = {'status':'unavailable', 'reason':'tablet templates are missing'}
    template, it_encoding, it_bom = decode_resource(template_it.read_bytes()) if templates_ready else ('', 'utf-8', b'')
    original_csd, encoding, bom = decode_resource(template_csd.read_bytes()) if templates_ready else ('', 'utf-8', b'')
    originals = BLOCKS.split(original_csd)
    existing_stats = {b.splitlines()[1].strip() for b in originals if b.startswith('description')}
    supplements = []
    for path in (template_map_csd, template_global_csd):
        if quotes and path and path.exists():
            for block in BLOCKS.split(decode_resource(path.read_bytes())[0]):
                if not block.startswith('description'):
                    continue
                key = block.splitlines()[1].strip()
                if key not in existing_stats:
                    existing_stats.add(key)
                    supplements.append(block)
    entries = {}; resource_rows = []; supported = set()
    for slug, modifiers in quotes.items():
        short = slug.removesuffix('_Tablet'); used = set(); edits = 0; blocks = []
        for block in originals:
            modified, found, changed = price_block(block, modifiers, ratio)
            blocks.append(modified); used.update(found); edits += changed
        for block in supplements:
            modified, found, changed = price_block(block, modifiers, ratio)
            if changed:
                blocks.append(modified); used.update(found); edits += changed
        unmatched = [q.identifier for q in modifiers if q.identifier not in used]
        if unmatched or not edits:
            raise ValueError(f'{slug}: game descriptions do not cover all selected prices: {unmatched}')
        text = clean_chinese_markup(''.join(blocks)); validate_csd(text)
        csd_name = f'data/statdescriptions/poe2price/{short.lower()}_tablet_stat_descriptions.csd'
        it_name = f'metadata/items/toweraugments/poe2price/{short.lower()}.it'
        it_text, replacements = re.subn(r'(?i)data/statdescriptions/tablet_stat_descriptions\.csd', csd_name, template)
        if replacements != 1:
            raise ValueError('tablet template reference must occur once')
        entries[csd_name] = bom + text.encode(encoding)
        entries[it_name] = it_bom + it_text.encode(it_encoding)
        supported.add(short)
        resource_rows.append({'tablet':slug,'modifiers':len(modifiers),'matched':len(used),
                              'changed':edits,'unmatched':unmatched})
    named, named_rows = price_tablet_names(clean_references(patched_baseitems.read_bytes()), ninja.get('base_prices', {}))
    if not supported and not named_rows: raise ValueError('no tablet descriptions matched and no base prices; layer skipped')
    redirected, count = _redirect_tablet_base_items(named, supported)
    if count != len(supported): raise ValueError('tablet base rows incomplete')
    entries[game_path] = redirected
    if english_baseitems and english_baseitems.exists() and english_baseitems.resolve() != source_baseitems.resolve():
        english_named, english_names = price_tablet_names(clean_references(english_baseitems.read_bytes()), ninja.get('base_prices', {}))
        if len(english_names) != len(named_rows): raise ValueError('English tablet name rows incomplete')
        english, en_count = _redirect_tablet_base_items(english_named, supported)
        if en_count != count: raise ValueError('English tablet base rows incomplete')
        entries['data/balance/baseitemtypes.datc64'] = english
    with zipfile.ZipFile(output_zip) as archive:
        previous = {info.filename:archive.read(info) for info in archive.infolist()
                    if not info.is_dir() and '/poe2price/' not in info.filename.lower()}
    previous.update(entries)
    validate_resources(previous)
    fd, temporary = tempfile.mkstemp(prefix='.tablet-', suffix='.zip', dir=output_zip.parent); os.close(fd)
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path, content in previous.items(): archive.writestr(path, content)
        os.replace(temporary, output_zip)
    finally: Path(temporary).unlink(missing_ok=True)
    patched_baseitems.write_bytes(redirected)
    status = 'ok' if all(source.get('status') == 'ok' for source in reports.values()) else 'partial'
    report = {'status':status, **reports, 'resources':resource_rows, 'redirected_items':count, 'base_names':named_rows,
              'price_display':'ascending_magic_rare_prices', 'price_pairs':pair_audit, 'game_mapping':mapping,
              'merge_rule':{'relative_gap_max':'20% to 10%, log interpolation',
                            'anchors':'P75 and max(P95, 2*P75), from query-consistent pairs',
                            'currencies':'dynamic E/C/D with one common rate revision',
                            'single_price':'mean_of_two_selected_prices', 'equal_formatted_values':'collapse'},
              'rarity_queries': {r: {'status': api_reports.get(r, {}).get('status'),
                                    'snapshot': api_reports.get(r, {}).get('snapshot'),
                                    'rows': api_reports.get(r, {}).get('rows', 0),
                                    'query_config': api_reports.get(r, {}).get('query_config', {})}
                                for r in ('magic', 'rare')},
              'reference_note':'词缀为市场参考价，非整件估价；数据源样本使用次数条件见 api.query_config'}
    resource_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
