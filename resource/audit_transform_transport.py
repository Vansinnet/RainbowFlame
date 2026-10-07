"""Audit actual per-frame/object matrix loads in the 36 original Soulblaze shaders."""
import json
import hashlib
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[4]


def sha(data):
    return hashlib.sha256(data).hexdigest()

OUT = ROOT / 'docs/analysis-rainbow-transform-transport-20260919-t1'
INPUTS = [
    ROOT / 'mods/active/RainbowFlame/analysis/enemy-follow-20260919-b1',
    ROOT / 'docs/analysis-rainbow-live-controls-20260919-e1/c509a3325ebb3385',
    ROOT / 'docs/analysis-rainbow-live-controls-20260919-e1/7a878519994efa78',
]


def inspect(text):
    defs = {key: value.split(';', 1)[0].rstrip() for key, value in
            re.findall(r'^  (%[\w.]+) = (.+)$', text, re.M)}
    buffers = []
    for name, ident, binding in re.findall(
            r'^; (\w+)\s+cbuffer\s+NA\s+NA\s+CB(\d+)\s+cb(\d+)\s+1\s*$', text, re.M):
        handles = [key for key, value in defs.items() if value ==
                   f'call %dx.types.Handle @dx.op.createHandle(i32 57, i8 2, i32 {ident}, i32 {binding}, i1 false)']
        assert len(handles) <= 1
        loads = []
        for key, value in defs.items():
            if not handles or '@dx.op.cbufferLoad' not in value or f'%dx.types.Handle {handles[0]},' not in value:
                continue
            match = re.fullmatch(r'call %dx.types.CBufRet\.(f32|i32) @dx.op.cbufferLoadLegacy\.\1\(i32 59, %dx.types.Handle %\w+, i32 (\d+)\)', value)
            assert match, 'Unsupported cbuffer addressing: ' + value
            extracts = []
            for dest, expression in defs.items():
                m = re.fullmatch(r'extractvalue %dx.types.CBufRet\.(?:f32|i32) ' + re.escape(key) + r', ([0-3])', expression)
                if m:
                    extracts.append(dict(value=dest, component=int(m[1]), byte=16*int(match[2])+4*int(m[1])))
            consumers = [dest for dest, expression in defs.items()
                         if re.search(re.escape(key) + r'(?![\w.])', expression)]
            assert set(consumers) == {e['value'] for e in extracts}, 'Non-extract aggregate consumer'
            loads.append(dict(value=key, register=int(match[2]), numeric_type=match[1], extracts=extracts))
        buffers.append(dict(name=name, id=int(ident), binding=int(binding), handle=handles,
                            loads=loads, accessed_bytes=sorted({e['byte'] for l in loads for e in l['extracts']})))
    stage = re.search(r'^define void @(\w+)\(', text, re.M)
    assert stage
    assert {key for key, expression in defs.items() if '@dx.op.cbufferLoad' in expression} == {
        load['value'] for buffer in buffers for load in buffer['loads']}, 'Unaccounted cbuffer load'
    return stage[1], buffers


def main():
    assert OUT.is_dir()
    rows = []
    for folder in INPUTS:
        for path in sorted(folder.glob('program-*.ll.txt')):
            text = path.read_text(encoding='utf-8')
            stage, buffers = inspect(text)
            rows.append(dict(path=str(path.relative_to(ROOT)), sha256=sha(path.read_bytes()), stage=stage, buffers=buffers))
            selected = [b for b in buffers if b['name'] in ('c_particle_system_per_frame', 'c_per_object')]
            print(folder.name, path.name, stage, [(b['name'], b['binding'], b['accessed_bytes']) for b in selected])
    assert len(rows) == 36
    with (OUT / 'matrix-loads.json').open('x', encoding='utf-8') as file:
        json.dump(rows, file, indent=2)
        file.write('\n')


if __name__ == '__main__':
    main()
