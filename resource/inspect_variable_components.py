"""Inspect component boundaries and source-named additional variable controls."""
import json
import struct
from inspect_variable_transport import ROOT, annotate, witness

OUT = ROOT / 'docs/analysis-rainbow-variable-bindings-20260919-s1'
EXACT = [
    'content/fx/particles/environment/expeditions/wastes/sand_tornado_01',
    'content/fx/particles/weapons/force_staff/3p_force_staff_explosion_indicator',
]


def rows(item):
    result = []
    for row in item['records']:
        w = row['prefix_words']
        result.append(dict(system=row['index'], kind=row['kind'], slots=row['slots'],
                           prefix_tail=w[130:], sections=row['section_offsets'],
                           behavior_hex=row['sections_hex'][0],
                           emitter_list_hex=row['sections_hex'][1],
                           emitter_hex=row['sections_hex'][2],
                           visualizer_hex=row['sections_hex'][3]))
    return result


def main():
    inventory = json.loads((OUT / 'inventory.json').read_text())
    output = []
    for p in inventory['particles'] + inventory['controls']:
        if p['variable_count']:
            output.append(dict(effect=p.get('path') or f"{p['identity'][1]:016x}",
                               variables=p['variables'], systems=rows(p)))
    for name in EXACT:
        path = witness.r.GAME / 'bundle' / f'{witness.r.murmur(name):016x}'
        if not path.exists():
            output.append(dict(effect=name, absent_standalone=True))
            continue
        raw_bundle = path.read_bytes()
        bundle = witness.bundle.fmt.read(raw_bundle, witness.bundle.baseline.decoder())
        matching = [p for p in witness.bundle.fmt.records(bundle)
                    if p['identity'][:2] == (witness.r.murmur('particles'), witness.r.murmur(name))]
        assert len(matching) == 1
        raw = matching[0]['raw']
        p = annotate(raw)
        with (OUT / (name.rsplit('/', 1)[-1] + '.particles')).open('xb') as file:
            file.write(raw)
        output.append(dict(effect=name, source=str(path), source_sha256=witness.sha(raw_bundle),
                           sha256=witness.sha(raw), variables=p['variables'], systems=rows(p)))
    with (OUT / 'components-corrected.json').open('x', encoding='utf-8') as file:
        json.dump(output, file, indent=2)
        file.write('\n')
    for p in output:
        print('\n', p['effect'], p.get('variables', 'ABSENT'))
        for row in p.get('systems', []):
            print('system', row['system'], 'kind', row['kind'], 'slots', row['slots'],
                  'tail', row['prefix_tail'], 'behavior', row['behavior_hex'],
                  'emitlist', row['emitter_list_hex'])


if __name__ == '__main__':
    main()
