"""Author only source-witnessed cloud identity words in the retained target."""
import hashlib
import importlib
import json
from pathlib import Path
import struct
import sys

import build

DOCS = build.WORKSPACE / 'docs'
T1 = DOCS / 'analysis-rainbow-live-controls-20260918-t1'
E1 = DOCS / 'analysis-flame-bundle-roundtrip-20260917-e1'
NAMES = ('RainbowFlame_stream_a', 'RainbowFlame_stream_b', 'RainbowFlame_stream_c')
OLD_IDS = (0xfbb1007d, 0xfe08df6a, 0xde38f24d)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sealed_tree(root):
    records = json.loads((root / 'SHA256SUMS.json').read_text())
    for name, record in records.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('Unsafe evidence path')
        data = path.read_bytes()
        if sha(data) != record['sha256']:
            raise ValueError('Evidence drift: ' + name)
    return sha((root / 'SHA256SUMS.json').read_bytes())


def dependencies():
    sealed_tree(T1)
    sealed_tree(E1)
    sys.path.insert(0, str(T1))
    sys.path.insert(0, str(E1))
    checks = importlib.import_module('check_contracts')
    fmt = importlib.import_module('format8')
    return checks, fmt


def positions(data, needle):
    result, p = [], 0
    while (p := data.find(needle, p)) >= 0:
        result.append(p)
        p += 1
    return result


def witness_check(checks):
    results = []
    for witness in json.loads((T1 / 'extraction.json').read_text()):
        body = (T1 / witness['particle']).read_bytes()[38:]
        rows = checks.prefixes(body)
        for name in checks.r.WITNESSES[witness['name']]:
            key = checks.r.murmur(name) >> 32
            hits = [r['start'] for r in rows if r['cloud_id32'] == f'{key:08x}']
            if len(hits) != 1 or positions(body, struct.pack('<I', key)) != hits:
                raise ValueError('Cloud witness failed')
            results.append(dict(name=name, id32=f'{key:08x}', body_offset=hits[0]))
    if len(results) != 4:
        raise ValueError('Incomplete cloud witnesses')
    return results


def rename(body, checks):
    rows = checks.prefixes(body)
    if len(rows) != 9 or tuple(int(r['cloud_id32'], 16) for r in rows[:3]) != OLD_IDS:
        raise ValueError('Not the exact target cloud profile')
    output = bytearray(body)
    mappings = []
    all_ids = {int(r['cloud_id32'], 16) for r in rows}
    for row, old, name in zip(rows, OLD_IDS, NAMES):
        key = checks.r.murmur(name) >> 32
        if key in all_ids or positions(body, struct.pack('<I', key)):
            raise ValueError('Authored ID collision')
        all_ids.add(key)
        if positions(body, struct.pack('<I', old)) != [row['start']]:
            raise ValueError('Unresolved internal cloud reference')
        struct.pack_into('<I', output, row['start'], key)
        mappings.append(dict(record=row['index'], name=name, old_id32=f'{old:08x}',
                             id32=f'{key:08x}', body_offset=row['start'],
                             raw_offset=38+row['start'], material=row['material_candidate']))
    after = checks.prefixes(output)
    for before, current in zip(rows, after):
        if {k: v for k, v in before.items() if k != 'cloud_id32'} != {
                k: v for k, v in current.items() if k != 'cloud_id32'}:
            raise ValueError('Particle structure changed')
    restored = bytearray(output)
    for row in mappings:
        struct.pack_into('<I', restored, row['body_offset'], int(row['old_id32'], 16))
    if restored != body:
        raise ValueError('Cloud-only roundtrip failed')
    return bytes(output), mappings


def author():
    checks, fmt = dependencies()
    witnesses = witness_check(checks)
    original = (E1 / 'stored.bundle').read_bytes()
    if sha(original) != '63ebd28c13c21c329a27547dc32dbd81b8b59ed53fba46d95abe0887eede6380':
        raise ValueError('Bundle identity')
    container = fmt.read(original)
    records = fmt.records(container)
    start, body, tail = records[0]['bodies'][0]
    if start != 38 or tail or sha(records[0]['raw']) != '7db926321d91441b40cbf5d376a3753cb60664f063da6656b04d838d20ade841':
        raise ValueError('Raw particle identity')
    renamed, mappings = rename(body, checks)
    # Include unaligned hits and every resource, not merely the parsed particle.
    references = []
    for mapping in mappings:
        hits = positions(container.logical, struct.pack('<I', int(mapping['old_id32'], 16)))
        if hits != [mapping['raw_offset']]:
            raise ValueError('Unresolved bundle cloud reference')
        references.append(dict(id32=mapping['old_id32'], logical_hits=hits))
    logical = container.logical[:start] + renamed + container.logical[start+len(body):]
    candidate = fmt.stored(container, logical)
    result = fmt.read(candidate)
    after = fmt.records(result)
    if result.prefix != container.prefix or result.final_padding != container.final_padding:
        raise ValueError('Format8 envelope changed')
    if len(after) != 19 or any(a['raw'] != b['raw'] for a, b in zip(records[1:], after[1:])):
        raise ValueError('Other resource changed')
    allowed = {m['raw_offset']+i for m in mappings for i in range(4)}
    delta = [i for i, (a, b) in enumerate(zip(container.logical, result.logical)) if a != b]
    if not set(delta) <= allowed or len(logical) != len(container.logical):
        raise ValueError('Unexpected logical diff')
    return candidate, after[0]['raw'], dict(
        status='AUTHORED CLOUD-RENAME NO-OP; NATIVE LOOKUP AND EXTERNAL REFERENCES UNTESTED',
        witnesses=witnesses, mappings=mappings, bundle_references=references,
        unchanged_other_resources=18, logical_changed_bytes=delta,
        original_bundle_sha256=sha(original), bundle_sha256=sha(candidate),
        raw_particle_sha256=sha(after[0]['raw']),
        scope='All 19 retained target-bundle resources. Not the complete game asset corpus.',
        shared_effect=True, expected_lookup=True, observed_lookup=None)
