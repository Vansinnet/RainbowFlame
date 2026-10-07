"""Prepare offline cloud no-op and fully roundtripped target export table models."""
import argparse
import ast
import json
from pathlib import Path
import struct

import build
import clouds
import shader_tables


def prepare(output):
    output = Path(output).resolve()
    if output.parent != build.WORKSPACE / 'docs' or not output.name.startswith('analysis-rainbow-live-controls-'):
        raise ValueError('Output must be a direct docs/analysis-rainbow-live-controls-* directory')
    if not output.is_dir() or (output / 'manifest.json').exists():
        raise ValueError('Prepare a unique output directory first')
    old, _, repack, _, _ = build.dependencies()
    models = []
    for info in repack.material_info():
        material = repack.material_original(info)
        _, _, offset, size = repack.material_sections(material)
        shader = material[offset:offset+size]
        begin, length = struct.unpack_from('<II', shader, 32)
        raw = shader[begin:begin+length]
        model = shader_tables.parse(raw)
        if shader_tables.serialize(model) != raw:
            raise ValueError('Original all-table roundtrip failed')
        reflected = []
        for label in ('first', 'second', 'third', 'fourth'):
            text = old.sealed(old.J1 / (info['material']+'-'+label+'.ll.txt'), old.J1).decode()
            fields = shader_tables.reflection_descriptors(text, old.murmur64)
            for field in fields.get('c_material_exports', []):
                hits = [d for d in model['buffers'][3]['descriptors'] if d[2] == field['hash']]
                # Bindless pseudo-fields intentionally share a resource hash and
                # are not named after the generated DXC field spelling.
                if field['name'].startswith('__BINDLESS_'):
                    continue
                if len(hits) != 1 or hits[0][3:] != [field['offset'], field['width']]:
                    raise ValueError('Descriptor and independent DXC reflection disagree')
                reflected.append(dict(program=label, **field, descriptor=hits[0]))
        serialized_model = {**model, 'techniques_opaque': model['techniques_opaque'].hex()}
        models.append(dict(material=info['material'], byte_length=length,
                           identity_roundtrip=True, model=serialized_model, independent_fields=reflected))
    candidate, particle, cloud_report = clouds.author()

    def save(name, data):
        with (output / name).open('xb') as out:
            out.write(data)

    def report(name, obj):
        save(name, (json.dumps(obj, indent=2)+'\n').encode())

    save('cloud-rename-NOOP-OFFLINE-UNTESTED.bundle', candidate)
    save('psyker_flame_staff_code_control.particles', particle)
    report('cloud-authoring.json', cloud_report)
    report('shader-table-models.json', models)
    inputs = {}
    for path in Path(__file__).parent.glob('*.py'):
        data = path.read_bytes()
        ast.parse(data)
        inputs[str(path.relative_to(build.WORKSPACE))] = dict(size=len(data), sha256=clouds.sha(data))
    report('implementation-inputs.json', inputs)
    report('manifest.json', dict(status='OFFLINE CLOUD NO-OP AND TABLE ROUNDTRIP; NOT LIVE-CONTROL READY',
                                cloud=cloud_report, materials=[dict(material=m['material'],
                                identity_roundtrip=m['identity_roundtrip'],
                                independent_fields=len(m['independent_fields'])) for m in models]))
    print(json.dumps(dict(cloud=cloud_report, material_tables=[(m['material'],len(m['independent_fields'])) for m in models]), indent=2))


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', required=True)
    prepare(cli.parse_args().output)
