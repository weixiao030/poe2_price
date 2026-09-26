"""Bind market identities to Stats using the current game's tablet Mods table."""
from dataclasses import replace
from pathlib import Path
import struct
import json

from poe2_tablet_refs import TYPES

# Official trade2 explicit IDs include both ordinary and powerful-boss wording.
# They are equivalent only when the alternative cannot roll on this tablet.
TRADE_STAT_GROUPS = (
    {'explicit.stat_358129101': 'map_spawn_extra_torment_spirits',
     'explicit.stat_775597083': 'maps_with_powerful_bosses_additional_spirit_+'},
    {'explicit.stat_3240183538': 'map_num_extra_strongboxes',
     'explicit.stat_3040603554': 'maps_with_powerful_bosses_additional_strongbox_+'},
    {'explicit.stat_395808938': 'map_extra_monoliths',
     'explicit.stat_2162684861': 'maps_with_powerful_bosses_additional_essence_+'},
    {'explicit.stat_1468737867': 'map_num_extra_shrines',
     'explicit.stat_3042527515': 'maps_with_powerful_bosses_additional_shrine_+'},
)


def bind_trade_query(quote, stat, available_stats):
    """Resolve known trade alternatives against this base's actual spawn pool."""
    aliases = next((group for group in TRADE_STAT_GROUPS if stat in group.values()), None)
    if not aliases or not quote.query_scope:
        return quote
    try:
        scope = json.loads(quote.query_scope)
        groups = scope[1]['stats']
        explicit = [(i, g) for i, g in enumerate(groups)
                    if any(f.get('id', '').startswith('explicit.') for f in g['filters'])]
        if len(explicit) != 1:
            return replace(quote, query_exact=False, query_reference=False)
        index, group = explicit[0]
        filters = group['filters']
        identifiers = [f['id'] for f in filters]
        shape = (group.get('type') == 'and' and len(filters) == 1 and set(group) == {'type', 'filters'}
                 or group.get('type') == 'count' and group.get('value') == {'min': 1}
                 and set(group) == {'type', 'value', 'filters'})
        if (not shape or not identifiers or not set(identifiers) <= aliases.keys()
                or any(set(f) != {'id'} for f in filters)):
            return replace(quote, query_exact=False, query_reference=False)
        possible = {identifier for identifier in identifiers if aliases[identifier] in available_stats}
        expected = {identifier for identifier, game_stat in aliases.items() if game_stat == stat}
        context = json.loads(quote.query_scope)
        del context[1]['stats'][index]
        if possible == expected:
            groups[index] = {'type': 'and', 'filters': [{'id': next(iter(expected))}]}
        return replace(quote, query_exact=possible == expected,
                       query_reference=expected < possible,
                       query_scope=json.dumps(scope, sort_keys=True, separators=(',', ':')),
                       query_context=json.dumps(context, sort_keys=True, separators=(',', ':')))
    except (ValueError, KeyError, TypeError, IndexError):
        return replace(quote, query_exact=False, query_reference=False)


class Table:
    def __init__(self, path, width):
        self.data = Path(path).read_bytes()
        self.count = struct.unpack_from('<I', self.data)[0]
        self.base = self.data.find(b'\xbb' * 8)
        self.width = width
        if not self.count or self.base != 4 + self.count * width:
            raise ValueError(f'unsupported tablet table layout: {Path(path).name}')

    def get(self, row, offset, fmt='Q'):
        if not 0 <= row < self.count:
            raise ValueError('tablet table reference out of bounds')
        return struct.unpack_from('<' + fmt, self.data, 4 + row * self.width + offset)

    def text(self, row, offset=0):
        start = self.base + self.get(row, offset)[0]
        end = start
        while self.base <= end < len(self.data) - 1:
            if self.data[end:end+2] == b'\0\0':
                return self.data[start:end].decode('utf-16-le')
            end += 2
        raise ValueError('invalid tablet table string')

    def array(self, row, offset, fmt='Q', stride=16):
        count, pointer = self.get(row, offset, 'QQ')
        if count > 10000 or count and self.base + pointer + count * stride > len(self.data):
            raise ValueError('invalid tablet table array')
        return [struct.unpack_from('<' + fmt, self.data, self.base + pointer + i * stride)[0]
                for i in range(count)]


def game_affix_catalog(*, mods_path, stats_path, tags_path, baseitems_path):
    """Enumerate positive-weight tablet mods, including those absent from the API."""
    mods, stats, tags, bases = (Table(mods_path, 693), Table(stats_path, 106),
                                Table(tags_path, 44), Table(baseitems_path, 360))
    base_tags = {}
    expected = {f'Metadata/Items/TowerAugment/{raw}Augment':kind+'_Tablet' for raw,kind in TYPES.items()}
    for row in range(bases.count):
        slug = expected.get(bases.text(row))
        if slug:
            base_tags[slug] = {tags.text(i) for i in bases.array(row, 104)} | {'default'}
    catalog = []
    for row in range(mods.count):
        if mods.get(row, 94, 'i')[0] != 34:
            continue
        gen = {1:'prefix', 2:'suffix'}.get(mods.get(row, 106, 'i')[0])
        if not gen:
            continue
        weight_tags = [tags.text(i) for i in mods.array(row, 158)]
        weights = mods.array(row, 677, 'i', 4)
        if len(weights) != len(weight_tags):
            raise ValueError('tablet spawn weights do not match tags')
        for slug, allowed in base_tags.items():
            weight = next((w for t,w in zip(weight_tags, weights) if t in allowed), 0)
            if weight <= 0:
                continue
            mod_id = mods.text(row)
            catalog.append({'tablet':slug, 'generation':gen, 'name':mods.text(row, 98),
                            'mod_id':mod_id, 'stat':stats.text(mods.get(row, 30)[0]),
                            'range':list(mods.get(row, 126, 'ii')), 'spawn_weight':weight})
    return catalog


def bind_game_stats(quotes, *, mods_path=None, stats_path=None, tags_path=None, baseitems_path=None,
                    game_catalog=None):
    if game_catalog is None:
        game_catalog = game_affix_catalog(mods_path=mods_path, stats_path=stats_path,
                                         tags_path=tags_path, baseitems_path=baseitems_path)
    catalog = {}; available_stats = {}
    for row in game_catalog:
        slug = row['tablet']
        available_stats.setdefault(slug, set()).add(row['stat'])
        for name in {row['name'], row['mod_id']} - {''}:
            catalog.setdefault((slug, row['generation'], name), []).append(row)
    bound = {}; audit = []
    for slug, rows in quotes.items():
        for quote in rows:
            matches = catalog.get((slug, quote.generation, quote.name), [])
            if len(matches) != 1:
                raise ValueError(f'tablet modifier identity is not unique: {slug}/{quote.generation}/{quote.name}')
            matched = matches[0]
            mod_id, stat = matched['mod_id'], matched['stat']
            quote = bind_trade_query(quote, stat, available_stats[slug])
            bound.setdefault(slug, []).append(replace(quote, stat=stat, game_range=tuple(matched['range'])))
            audit.append({'tablet':slug,'id':quote.identifier,'mod_id':mod_id,'stat':stat,'label':quote.label})
    return bound, audit


def report_game_coverage(game_catalog, quoted_mapping):
    quoted = {(row['tablet'], row['mod_id']) for row in quoted_mapping}
    missing = [row for row in game_catalog if (row['tablet'], row['mod_id']) not in quoted]
    return {'status':'partial' if missing else 'ok', 'game_combinations':len(game_catalog),
            'quoted_combinations':len(quoted), 'missing_quotes':missing,
            'scope':'positive spawn weights in the current game tables; live availability may have additional conditions'}
