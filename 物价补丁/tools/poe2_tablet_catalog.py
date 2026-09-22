"""Bind market identities to Stats using the current game's tablet Mods table."""
from dataclasses import replace
from pathlib import Path
import struct

from poe2_tablet_refs import TYPES


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


def bind_game_stats(quotes, *, mods_path, stats_path, tags_path, baseitems_path):
    mods, stats, tags, bases = (Table(mods_path, 693), Table(stats_path, 106),
                                Table(tags_path, 44), Table(baseitems_path, 360))
    base_tags = {}
    expected = {f'Metadata/Items/TowerAugment/{raw}Augment':kind+'_Tablet' for raw,kind in TYPES.items()}
    for row in range(bases.count):
        slug = expected.get(bases.text(row))
        if slug:
            base_tags[slug] = {tags.text(i) for i in bases.array(row, 104)} | {'default'}
    catalog = {}
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
            for name in {mods.text(row, 98), mod_id} - {''}:
                key = slug, gen, name
                catalog.setdefault(key, []).append((mod_id, stats.text(mods.get(row, 30)[0])))
    bound = {}; audit = []
    for slug, rows in quotes.items():
        for quote in rows:
            matches = catalog.get((slug, quote.generation, quote.name), [])
            if len(matches) != 1:
                raise ValueError(f'tablet modifier identity is not unique: {slug}/{quote.generation}/{quote.name}')
            mod_id, stat = matches[0]
            bound.setdefault(slug, []).append(replace(quote, stat=stat))
            audit.append({'tablet':slug,'id':quote.identifier,'mod_id':mod_id,'stat':stat,'label':quote.label})
    return bound, audit
