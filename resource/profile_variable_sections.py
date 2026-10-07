"""Validate finite compiled section grammar and expose exact variable-like records.

Structural tags are reported as numbers, not invented native instruction names.
"""
import json
import struct
from inspect_variable_transport import ROOT, witness

OUT = ROOT / 'docs/analysis-rainbow-variable-bindings-20260919-s1'


def main():
    data = json.loads((OUT / 'inventory.json').read_text())
    result, gpu, initializers = [], [], []
    for p in data['particles'] + data['controls']:
        name = p.get('path') or f"{p['identity'][1]:016x}"
        for row in p['records']:
            w = row['prefix_words']
            b = [bytes.fromhex(x) for x in row['sections_hex']]
            assert len(b[1]) == 5 * w[135]
            table = [struct.unpack_from('<BI', b[1], i*5) for i in range(w[135])]
            assert all(0 <= a[1] <= len(b[2]) for a in table)
            assert all(a[1] <= c[1] for a, c in zip(table, table[1:]))
            entries = []
            for i, (tag, offset) in enumerate(table):
                end = table[i+1][1] if i+1 < len(table) else len(b[2])
                value = b[2][offset:end]
                entries.append(dict(tag=tag, offset=offset, bytes=len(value), hex=value.hex()))
            # The same (tag, offset) table exists in stock CPU and GPU records.
            # This establishes extents, not the native semantics of its entries.
            item = dict(effect=name, system=row['index'], kind=row['kind'],
                        declared_variables=p['variables'], initializer_count=w[133],
                        initializer_bytes=len(b[0]), controllers=entries)
            if row['kind'] == 4:
                assert w[133] == 0 and not b[0] and row['slots'] == 0
                item['simple_rate_or_burst'] = (len(table) == 1 and
                    table[0] in ((12, 0), (13, 0)) and
                    len(b[2]) == (100 if table[0][0] == 12 else 88))
                gpu.append(item)
            if p['variable_count']:
                result.append(item)
                # A narrowly witnessed terminal record, with variable ordinal
                # hypothesis stated explicitly rather than treated as executable.
                for offset in range(0, len(b[0]) - 15, 4):
                    tag, destination, width, ordinal = struct.unpack_from('<4I', b[0], offset)
                    if tag == 21 and width in (1, 3) and ordinal < p['variable_count']:
                        initializers.append(dict(effect=name, system=row['index'],
                            relative_offset=row['section_offsets'][0] + offset,
                            tag=tag, destination=destination, width=width, ordinal=ordinal,
                            variable=p['variables'][ordinal], terminal=offset + 16 == len(b[0])))
    report = dict(profile='structural, not a native evaluator specification',
                  gpu=gpu, variable_controls=result, ordinal_candidates=initializers)
    with (OUT / 'section-profile.json').open('x', encoding='utf-8') as file:
        json.dump(report, file, indent=2)
        file.write('\n')
    print('GPU records (including retained duplicate controls):', len(gpu))
    print('All GPU initializers empty; exceptional controller lists:')
    for p in gpu:
        if not p['simple_rate_or_burst']:
            print(p)
    print('Variable-like initializer records:', len(initializers))
    for p in result:
        special = [c for c in p['controllers'] if c['tag'] in (17, 19, 20, 25, 26)]
        if special:
            print(p['effect'], p['system'], special)


if __name__ == '__main__':
    main()
