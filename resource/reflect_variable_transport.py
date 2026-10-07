"""Trace selected new GPU witnesses to authenticated, independently reflected DXIL."""
import importlib
import json
import re
import struct
import sys
from inspect_variable_transport import ROOT, witness

OUT = ROOT / 'docs/analysis-rainbow-variable-bindings-20260919-s1'
sys.path.insert(0, str(ROOT / 'mods/active/RainbowFlame/analysis/enemy-follow-20260919-b1'))
decoder = importlib.import_module('decode_surface')
build = importlib.import_module('build')
tables = importlib.import_module('shader_tables')


def save(path, data):
    if path.exists():
        assert path.read_bytes() == data
    else:
        with path.open('xb') as file:
            file.write(data)


def main():
    source = ROOT / 'docs/analysis-rainbow-global-soulblaze-deployment-20260919-m1/30ebeee18093c079.installed-before.rollback'
    data = source.read_bytes()
    assert witness.sha(data) == witness.bundle.STOCK_SHA
    bundle, _ = witness.bundle.read(data, witness.bundle.baseline.decoder())
    by_id = {p['identity'][:2]: p for p in witness.bundle.fmt.records(bundle)}
    # Valkyrie complete three-stage chain; both renegade explosion emitters.
    pending = ['5cf898e4c78444c9', '745c933711627e90', '94505880cdb5dd02',
               '70762e2bcb639c83', 'f7d2c7487e3435f3']
    materials = []
    while pending:
        key = pending.pop(0)
        if any(p['id'] == key for p in materials):
            continue
        assert len(materials) < 20
        raw = by_id[(witness.r.murmur('material'), int(key, 16))]['raw']
        assert len(raw) == 68 and struct.unpack_from('<IBIBI', raw, 24) == (0, 1, 30, 1, 0)
        reference = raw[38:].split(b'\0')[0].decode('ascii')
        assert reference.startswith('data/') and '..' not in reference
        data = (witness.r.GAME / 'bundle' / reference).read_bytes()
        info = witness.r.parse(data)
        save(OUT / (key + '.material'), data)
        materials.append(dict(id=key, reference=reference, sha256=witness.sha(data), parsed=info))
        if not info['shader_size']:
            pending.extend(p for p in info['parent_hashes'] if int(p, 16))
    old, _, _, reflection, _ = build.dependencies()
    prepare, parser = old.prior()
    dxc = prepare.Dxc()
    for material in materials:
        info = material['parsed']
        if not info['shader_size']:
            continue
        data = (OUT / (material['id'] + '.material')).read_bytes()
        shader = data[info['shader_offset']:info['shader_offset'] + info['shader_size']]
        header = struct.unpack_from('<12I', shader)
        start, length = header[10:12]
        end = start + length
        assert header[0] == 43 and 48 <= start < end <= header[5] <= len(shader)
        folder = OUT / material['id']
        folder.mkdir(exist_ok=True)
        programs, position = [], start
        while True:
            begin = shader.find(b'\x8c\x06', position, end)
            if begin < 0:
                break
            position = begin + 2
            if begin < start + 8 or begin + 5 > end:
                continue
            envelope, length = struct.unpack_from('<II', shader, begin - 8)
            finish = begin + length
            if envelope != 1 or not begin + 8 <= finish <= end - 16:
                continue
            frame = shader[begin:finish]
            if int.from_bytes(frame[2:5], 'big') + 1 != len(frame) - 5:
                continue
            kind, decoded_length, key = struct.unpack_from('<IIQ', shader, finish)
            if kind != 5 or old.murmur64(frame) != key:
                continue
            assert 32 <= decoded_length <= 2000000 and len(programs) < 64
            decoded = parser.decompress(frame, decoded_length)
            decoder.dxbc(decoded)
            validated, message = dxc.operation(decoded, assemble=False)
            assert not message and validated == decoded
            path = folder / f'program-{len(programs):02d}.dxbc'
            save(path, decoded)
            text = reflection.dump(path)
            save(path.with_suffix('.ll.txt'), text)
            source = text.decode()
            entry = re.search(r'define void @(\w+)\(', source)
            assert entry
            fields = tables.reflection_descriptors(source, old.murmur64)
            programs.append(dict(stage=entry[1], sha256=witness.sha(decoded), dxc_valid=True,
                                 buffers=fields))
            position = finish
        assert programs
        material['programs'] = programs
        print(material['id'], len(programs), sorted({p['stage'] for p in programs}))
    save(OUT / 'new-reflection.json', (json.dumps(materials, indent=2) + '\n').encode())


if __name__ == '__main__':
    main()
