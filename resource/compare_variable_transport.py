"""Compare exact serialized sections without assigning undocumented opcodes."""
import json
import struct
from inspect_variable_transport import ROOT, witness

OUT = ROOT / 'docs/analysis-rainbow-variable-bindings-20260919-s1'


def main():
    report = json.loads((OUT / 'inventory.json').read_text())
    assert witness.sha((OUT / 'inventory.json').read_bytes()) == '88193ccabd54d6138f0bcea3a2677fce222349701dde211c9a25f483b93e06aa'
    selected = [p for p in report['particles'] if p['variable_count'] and
                any(r['kind'] == 4 for r in p['records'])]
    selected += [report['controls'][0], report['controls'][-1], report['controls'][-2]]
    names = {}
    dictionary = witness.r.TEMP / 'parser-reference/bitsquid/murmur/dictionaries/dictionary_hashcat_dt.txt'
    wanted = {p['identity'][1] for p in selected if 'identity' in p}
    for name in dictionary.read_text(encoding='utf-8').splitlines():
        key = witness.r.murmur(name)
        if key in wanted:
            names[f'{key:016x}'] = name
    rows = []
    for p in selected:
        name = p.get('path') or names.get(f"{p['identity'][1]:016x}", f"{p['identity'][1]:016x}")
        print('\nEFFECT', name, 'variables', p['variables'])
        for row in p['records']:
            if row['kind'] != 4:
                continue
            print('SYSTEM', row['index'], 'sections', row['section_offsets'])
            w = row['prefix_words']
            for offset in range(0, 576, 16):
                words = w[offset//4:offset//4+4]
                if any(words):
                    floats = struct.unpack('<4f', struct.pack('<4I', *words))
                    print(f'{offset:03d}', ' '.join(f'{x:08x}' for x in words),
                          ' '.join(f'{x:.6g}' for x in floats))
            for i, section in enumerate(row['sections_hex']):
                print('SECTION', i, section)
            rows.append(dict(effect=name, system=row))
    with (OUT / 'selected-systems.json').open('x', encoding='utf-8') as file:
        json.dump(dict(names=names, systems=rows), file, indent=2)
        file.write('\n')


if __name__ == '__main__':
    main()
