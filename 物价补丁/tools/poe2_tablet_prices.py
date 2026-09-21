"""Optional tablet market layers. Generate validated resources before committing ZIP."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
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
    converted = row.get("converted") or {}
    if str(converted.get("currency", "")).lower() in {"exalted", "exalted orb"}:
        # An incomplete conversion must not silently turn a subset into the total.
        if converted.get("missing_count", 0):
            return Decimal(0)
        for key in ("low_sample_median", "median", "min"):
            if decimal(converted.get(key)) > 0:
                return decimal(converted[key])
    rates = rates or {}
    values = []
    for unit, sample in (row.get("prices") or {}).items():
        if not isinstance(sample, dict):
            continue
        value = next((decimal(sample[k]) for k in ("low_sample_median", "median", "min")
                      if decimal(sample.get(k)) > 0), Decimal(0))
        if unit != "exalted":
            if decimal(rates.get("exalted")) <= 0 or decimal(rates.get(unit)) <= 0:
                continue
            value *= decimal(rates[unit]) / decimal(rates["exalted"])
        if value > 0:
            values.append(value)
    # Separate-currency medians cannot reconstruct a combined median. Only use
    # the raw fallback when there is exactly one complete currency group.
    return values[0] if len(values) == 1 and len(row.get("prices") or {}) == 1 else Decimal(0)


def fetch_tablet_affix_prices(client, api_base, league):
    if not league:
        raise ValueError("tablet league is required")
    result = {}; offset = 0; snapshot = None; total = None; seen = set(); pages = 0; rates = {}
    while True:
        query = urllib.parse.urlencode(dict(league=league, display_currency="exalted", sort="name", limit=200, offset=offset))
        payload = client.get_json(api_base.rstrip('/') + '/api/v1/prices?' + query)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("invalid tablet prices response")
        state = payload.get("snapshot") or {}
        exchange = payload.get("exchange_rates") or {}
        if state.get("league") != league or exchange.get("league") != league:
            raise ValueError("tablet API league does not match selection")
        if state.get("stale") is not False or exchange.get("stale") is not False:
            raise ValueError("tablet API snapshot or exchange rates are stale")
        if not state.get("id") or snapshot and state["id"] != snapshot:
            raise ValueError("tablet snapshot changed during pagination")
        if total is not None and payload.get("total") != total:
            raise ValueError("tablet pagination total changed")
        snapshot = state["id"]; total = int(payload.get("total", 0)); pages += 1
        if total <= 0 or total > 12000 or int(payload.get("offset", -1)) != offset:
            raise ValueError("invalid tablet pagination")
        current_rates = {k: decimal(v) for k, v in exchange.get("values", {}).items()}
        current_rates["divine"] = Decimal(1)
        if rates and rates != current_rates:
            raise ValueError("tablet exchange rates changed during pagination")
        rates = current_rates
        for row in payload["data"]:
            identifier = row.get("id")
            if not identifier or identifier in seen:
                raise ValueError("tablet pagination contains missing or duplicate IDs")
            seen.add(identifier)
            slug = row.get("tablet")
            if slug not in TABLET_SLUGS or row.get("status") != "ok" or int(row.get("sample_count", 0)) <= 0:
                continue
            text = str(row.get("text_en") or "")
            value = _tablet_price_from_row(row, rates)
            if not text or value <= 0:
                continue
            numbers = re.findall(r'\((\d+)-(\d+)\)|(\b\d+\b)', text)
            bounds = [(int(a or c), int(b or c)) for a, b, c in numbers]
            # More numbers can be literal caps, not additional stats. The game
            # template resolves them before pricing; never discard the quote.
            ranges = [(int(a), int(b)) for a, b, c in numbers if a]
            low, high = ranges[0] if len(ranges) == 1 else bounds[0] if len(bounds) == 1 else (None, None)
            result.setdefault(slug, []).append(Quote(text, value, low, high))
        size = len(payload["data"]); offset += size
        if offset == total:
            break
        if not size or offset > total or pages >= 60:
            raise ValueError("incomplete tablet snapshot")
    return result, {"league": league, "snapshot": snapshot, "pages": pages, "total": total,
                    "rows": sum(map(len, result.values())), "rates": {k: str(v) for k, v in rates.items()},
                    "query_config": state.get("config", {})}


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
            # Split overlapping tier queries into disjoint intervals and choose
            # the cheapest applicable reference; never inflate by max merging.
            cuts = sorted({n for low, high, _ in candidates for n in (low, high + 1 if high is not None else None) if n is not None})
            ranges = []
            if candidates and all(low is None and high is None for low, high, _ in candidates):
                ranges = [(None, None, min((q for _, _, q in candidates), key=lambda q:q.price))]
            else:
                for low, end in zip(cuts, cuts[1:]):
                    applicable = [q for lo, hi, q in candidates if (lo is None or lo <= low) and (hi is None or end - 1 <= hi)]
                    if applicable: ranges.append((low, end - 1, min(applicable, key=lambda q:q.price)))
            additions = []
            for low, high, quote in ranges:
                condition = '#' if low is None and high is None else str(low) if low == high else f"{low if low is not None else '#'}|{high if high is not None else '#'}"
                price = format_price(quote.price, ratio)
                if not price: continue
                additions.append(f'{record[1]}{condition} "{record[3]}={price}"{record[4]}{record[5]}')
                # Several market queries can cover the same game value. Count
                # them as covered only after emitting its cheapest price branch.
                used.update(q.text for lo, hi, q in candidates
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
                                english_baseitems=None, template_map_csd=None, template_global_csd=None):
    reports = {}; quotes = {}; ninja = {}
    try:
        quotes, reports['api'] = fetch_tablet_affix_prices(client, api_base, league)
        reports['api']['status'] = 'ok'
    except Exception as exc:
        reports['api'] = {'status':'unavailable', 'reason':f'{type(exc).__name__}: {exc}'}
    try:
        ninja = fetch_poe_ninja_precursor_tablets(client, league)
        reports['poe_ninja_precursor_tablets'] = ninja
    except Exception as exc:
        reports['poe_ninja_precursor_tablets'] = {'status':'unavailable', 'reason':f'{type(exc).__name__}: {exc}'}
    rates = reports.get('api', {}).get('rates', {})
    ratio = 1 / decimal(rates['exalted']) if decimal(rates.get('exalted')) > 0 else decimal(ninja.get('divine_exalted'))
    if ratio <= 0 or not quotes and not ninja.get('prices'):
        raise ValueError('tablet price sources unavailable; ' + json.dumps(reports, ensure_ascii=False))
    templates_ready = bool(template_it and template_it.exists() and template_csd and template_csd.exists())
    if quotes and not templates_ready:
        reports['affix_templates'] = {'status':'unavailable', 'reason':'tablet templates are missing'}
    template, it_encoding, it_bom = decode_resource(template_it.read_bytes()) if templates_ready else ('', 'utf-8', b'')
    original_csd, encoding, bom = decode_resource(template_csd.read_bytes()) if templates_ready else ('', 'utf-8', b'')
    supplements = []
    for path in (template_map_csd, template_global_csd):
        if templates_ready and quotes and path and path.exists():
            supplements.extend(BLOCKS.split(decode_resource(path.read_bytes())[0])[1:])
    existing_stats = {b.splitlines()[1].strip() for b in BLOCKS.split(original_csd)[1:]}
    supplements = [b for b in supplements if b.splitlines()[1].strip() not in existing_stats]
    quoted_keys = {_tablet_text_key(q.text) for values in quotes.values() for q in values}
    supplements = [b for b in supplements if any(
        _tablet_text_key(record[3]) in quoted_keys for line in b.split('lang "')[0].splitlines(keepends=True)
        if (record := LINE.match(line)))]
    entries = {}; resource_rows = []; supported = set()
    for slug in TABLET_SLUGS:
        modifiers = quotes.get(slug, [])
        if not modifiers or not templates_ready: continue
        short = slug.removesuffix('_Tablet'); used = set(); edits = 0
        blocks = []
        for block in BLOCKS.split(original_csd):
            modified, found, count = price_block(block, modifiers, ratio)
            blocks.append(modified); used.update(found); edits += count
        for block in supplements:
            modified, found, count = price_block(block, modifiers, ratio)
            if count: blocks.append(modified); used.update(found); edits += count
        if not edits: continue
        text = clean_chinese_markup(''.join(blocks)); validate_csd(text)
        csd_name = f'data/statdescriptions/poe2price/{short.lower()}_tablet_stat_descriptions.csd'
        it_name = f'metadata/items/toweraugments/poe2price/{short.lower()}.it'
        it_text, replacements = re.subn(r'(?i)data/statdescriptions/tablet_stat_descriptions\.csd', csd_name, template)
        if replacements != 1: raise ValueError('tablet template reference must occur once')
        entries[csd_name] = bom + text.encode(encoding)
        entries[it_name] = it_bom + it_text.encode(it_encoding)
        supported.add(short)
        resource_rows.append({'tablet':slug, 'modifiers':len(modifiers), 'matched':len(used), 'changed':edits,
                              'unmatched':[q.text for q in modifiers if q.text not in used]})
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
              'reference_note':'词缀为市场参考价，非整件估价；数据源样本使用次数条件见 api.query_config'}
    resource_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
