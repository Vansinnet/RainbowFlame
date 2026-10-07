"""Bounded 3P material reflection; no deployment or runtime mutation."""
import hashlib
import importlib
import json
from pathlib import Path
import re
import struct
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / 'docs/analysis-rainbow-staff-3p-20260921-a1/layers'
A1 = ROOT / 'docs/analysis-flame-target-20260917-a1'
K1 = ROOT / 'docs/analysis-flame-ramp-20260918-k1/materials'
sys.path.insert(0, str(A1))
parse_materials = importlib.import_module('parse_materials')
build = importlib.import_module('build')


def save(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f'Existing artifact differs: {path}')
    else:
        with path.open('xb') as stream:
            stream.write(data)


def main():
    OUT.mkdir(exist_ok=True)
    missing = Path(r'D:\Steam\steamapps\common\Warhammer 40,000 DARKTIDE\bundle\data\03\03f68803faf03b51')
    retained = OUT / '20b91c9f8a8cc4aa.material'
    if not retained.exists():
        data = missing.read_bytes()
        if hashlib.sha256(data).hexdigest() != '73943bfb02628b95f6e822cddfea241e87feaa7849080f157952a012cb7efce3':
            raise ValueError('Previously observed 3P material identity changed')
        save(retained, data)
    sources = [retained,
               A1 / 'materials-4e6163c275b96d00-v8-stream/hash-only/69eeb7e1c5363ec1.material',
               *[K1 / (key + '.material') for key in ('e14900c258cc9b8e', '84dce57f22a9d409', 'ec97645dbad0d25c')]]
    old, _, _, reflection, _ = build.dependencies()
    prepare, parser = old.prior()
    dxc = prepare.Dxc()
    results = []
    for path in sources:
        data = path.read_bytes()
        info = parse_materials.parse(data)
        folder = OUT / path.stem
        folder.mkdir(exist_ok=True)
        shader = data[info['shader_offset']:info['shader_offset'] + info['shader_size']]
        header = struct.unpack_from('<12I', shader)
        start, length = header[10:12]
        end = start + length
        if header[0] != 43 or not 48 <= start < end <= header[5] <= len(shader):
            raise ValueError('Unrecognized shader device bounds')
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
            kind, size, key = struct.unpack_from('<IIQ', shader, finish)
            if kind != 5 or old.murmur64(frame) != key:
                continue
            if not 32 <= size <= 2000000 or len(programs) >= 256:
                raise ValueError('Shader program bound exceeded')
            decoded = parser.decompress(frame, size)
            validated, message = dxc.operation(decoded, assemble=False)
            if message or validated != decoded:
                raise ValueError('Shader validation failed')
            target = folder / f'program-{len(programs):02d}.dxbc'
            save(target, decoded)
            text = reflection.dump(target)
            save(target.with_suffix('.ll.txt'), text)
            entry = re.search(rb'define void @(\w+)\(', text)
            programs.append(dict(stage=entry[1].decode() if entry else None,
                                 sha256=hashlib.sha256(decoded).hexdigest(), frame=[begin, finish]))
            position = finish
        results.append(dict(material=path.stem, source=str(path.relative_to(ROOT)),
                            sha256=hashlib.sha256(data).hexdigest(), parsed=info, programs=programs))
        print(path.stem, len(programs), sorted({str(p['stage']) for p in programs}))
    save(OUT / 'reflection.json', (json.dumps(results, indent=2) + '\n').encode())


if __name__ == '__main__':
    main()
