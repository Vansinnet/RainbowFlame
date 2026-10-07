"""Bounded offline effect inventory and byte annotations; never deploys resources."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'docs/analysis-rainbow-surface-variables-20260919-r1'))
witness = importlib.import_module('inspect_variables')


def annotate(raw):
    result = witness.inspect(raw)
    body = raw[38:]
    for row in result['records']:
        start, end = row['start'], row['end']
        row['prefix_words'] = list(struct.unpack_from('<144I', body, start))
        row['prefix_float4_rows'] = [list(struct.unpack_from('<4f', body, start + p))
                                     for p in range(0, 576, 16)]
        row['sections_hex'] = [body[start + a:start + b].hex() for a, b in
                               zip(row['section_offsets'], row['section_offsets'][1:])]
        if row['kind'] == 4:
            row['materials'] = [f'{struct.unpack_from("<Q", body, row["visualizer"] + 12 + 16*i)[0]:016x}'
                                for i in range(3)]
        assert end <= len(body)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    assert out.is_dir() and out.is_relative_to(ROOT / 'docs')
    target = out / 'inventory.json'
    assert not target.exists(), 'Refusing to overwrite evidence'
    source = ROOT / 'docs/analysis-rainbow-global-soulblaze-deployment-20260919-m1/30ebeee18093c079.installed-before.rollback'
    data = source.read_bytes()
    assert witness.sha(data) == witness.bundle.STOCK_SHA
    bundle, blocks = witness.bundle.read(data, witness.bundle.baseline.decoder())
    assert witness.bundle.serialize(bundle, blocks) == data
    records = witness.bundle.fmt.records(bundle)
    results, rejected = [], []
    for index, record in enumerate(records):
        if record['identity'][0] != witness.r.murmur('particles'):
            continue
        try:
            item = annotate(record['raw'])
        except (ValueError, struct.error, AssertionError) as error:
            rejected.append(dict(index=index, identity=list(record['identity']), error=str(error)))
            continue
        item.update(index=index, identity=list(record['identity']))
        results.append(item)
    controls = []
    manifest = json.loads((witness.OUT / 'variables.json').read_text())
    for control in manifest['controls']:
        raw = (ROOT / control['path']).read_bytes()
        assert witness.sha(raw) == control['sha256']
        controls.append(dict(path=control['path'], **annotate(raw)))
    report = dict(source=str(source.relative_to(ROOT)), sha256=witness.sha(data),
                  resource_count=len(records), noop_roundtrip=True,
                  particles=results, rejected=rejected, controls=controls)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print('Resources:', len(records), 'particles:', len(results), 'rejected:', len(rejected))
    for item in results:
        gpu = [r for r in item['records'] if r['kind'] == 4]
        if item['variable_count'] or gpu:
            print(f"{item['identity'][1]:016x}", 'variables=', item['variables'],
                  'GPU=', [(r['index'], r['materials']) for r in gpu])
    print('Report SHA256:', hashlib.sha256(target.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
