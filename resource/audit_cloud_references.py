"""Finite offline reference audit: current Lua literals and retained material streams."""
import json
import re
import struct

import build
import clouds


def audit():
    old, _, _, _, _ = build.dependencies()
    source = build.WORKSPACE/'darktide-source'
    source_hits, files, total = [], 0, 0
    for path in source.rglob('*.lua'):
        data = path.read_bytes()
        if len(data)>4*1024*1024:
            raise ValueError('Source file exceeds audit bound')
        files += 1
        total += len(data)
        # Literal token audit, not a Lua interpreter: escaped/dynamic strings
        # cannot establish a cloud name and remain outside this finite claim.
        for match in re.finditer(rb'''["']([^"'\r\n\\]*)["']''',data):
            key = old.murmur64(match[1]) >> 32
            if key in clouds.OLD_IDS:
                source_hits.append(dict(path=str(path.relative_to(build.WORKSPACE)),
                                        byte_offset=match.start(1), literal=match[1].decode('utf-8'),id32=f'{key:08x}'))
    references = []
    root = clouds.DOCS/'analysis-flame-target-20260917-a1/materials-4e6163c275b96d00-v8-stream'
    for path in root.rglob('*.material'):
        data = path.read_bytes()
        references.append(dict(path=str(path.relative_to(build.WORKSPACE)),sha256=clouds.sha(data),
                               hits={f'{key:08x}':clouds.positions(data,struct.pack('<I',key)) for key in clouds.OLD_IDS}))
    result = dict(source_files=files,source_bytes=total,source_literal_hits=source_hits,
                  retained_materials=references,
                  boundary='Not all game bundles; dynamic/escaped Lua strings and native consumers remain unproved.')
    output = clouds.DOCS/'analysis-rainbow-live-controls-20260918-u1/cloud-external-reference-audit.json'
    with output.open('x',encoding='utf-8') as out:
        out.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    audit()
