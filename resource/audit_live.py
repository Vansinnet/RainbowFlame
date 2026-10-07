"""Independent sealed pre-live reader and packed-profile regression; offline only."""
import ast
import hashlib
import json
import struct
from typing import Callable, cast

import build

ROOT = build.WORKSPACE/'docs/analysis-rainbow-live-controls-20260918-u1'


def audit():
    a1 = build.WORKSPACE/'docs/analysis-flame-target-20260917-a1'
    seal = {r['path']:r for r in json.loads((a1/'SHA256SUMS.json').read_text())}
    for name in ('parse_materials.py','reference-limn/src/file/material.rs',
                 'reference-parser/bitsquid/stingray/material.py'):
        data = (a1/name).read_bytes()
        assert len(data) == seal[name]['size']
        assert hashlib.sha256(data).hexdigest() == seal[name]['sha256']
    tree = ast.parse((a1/'parse_materials.py').read_text())
    nodes: list[ast.stmt] = [n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef))
             and n.name in ('Cursor','parse')]
    scope: dict[str, object] = {'struct':struct}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'sealed-pre-live-reader','exec'),scope)
    rows = []
    for name in ('a8dc696a363ec3d3','49697971309d8a04'):
        old = build.WORKSPACE/'docs/analysis-flame-huecycle-build-20260918-o1'
        paths = [(kind,old/(name+'-'+kind+'.material')) for kind in ('identity','noop','huecycle')]
        paths += [(kind,ROOT/kind/(name+'.material')) for kind in ('live-v3','live-v4')]
        for kind,path in paths:
            data = path.read_bytes()
            parsed = cast(Callable[[bytes], dict],scope['parse'])(data)
            version,mo,ms,so,ss,tail,ts = struct.unpack_from('<7I',data)
            assert version == 61 and mo == 28 and so+ss == tail and tail+ts == len(data)
            assert parsed['shader_offset'] == so and parsed['material_offset']+parsed['material_size'] == mo+ms
            assert struct.unpack_from('<I',data,so)[0] == 43
            end_word = struct.unpack_from('<I',data,mo+ms)[0]
            packed = mo+ms == so and end_word == 43
            assert packed == (kind != 'live-v3' or name != '49697971309d8a04')
            rows.append(dict(build=kind,material=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),
                             template_end=mo+ms,shader_start=so,word_at_template_end=end_word,
                             packed=packed,parsed=parsed))
        prior = (ROOT/'live-v3'/(name+'.material')).read_bytes()
        current = (ROOT/'live-v4'/(name+'.material')).read_bytes()
        if name.startswith('a8'):
            assert prior == current
        else:
            expected = bytearray(prior[:428]+prior[432:])
            struct.pack_into('<I',expected,12,428)
            struct.pack_into('<I',expected,20,struct.unpack_from('<I',prior,20)[0]-4)
            assert current == expected
    return rows


if __name__ == '__main__':
    result = audit()
    with (ROOT/'live-v4/independent-audit.json').open('x') as stream:
        json.dump(result,stream,indent=2)
    files = [dict(path=p.name,size=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
             for p in sorted((ROOT/'live-v4').iterdir()) if p.is_file()]
    with (ROOT/'live-v4/SHA256SUMS.json').open('x') as stream:
        json.dump(files,stream,indent=2)
    print('10 independent parses; 9 packed layouts; rejected v3/49 gap reproduced; v4 exact minimal byte delta.')
