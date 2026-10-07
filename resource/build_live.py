"""Build experimental live-parameter materials offline; never deploys or connects."""
import argparse
import json
from pathlib import Path
import re
import struct

import build
import clouds
import export_resources
import live_shader
import shader_tables


def run(output, include_original=False):
    output = Path(output).resolve()
    root = output if output.parent == build.WORKSPACE/'docs' else output.parent
    if root.parent != build.WORKSPACE / 'docs' or not root.name.startswith('analysis-rainbow-live-controls-'):
        raise ValueError('Use a direct docs/analysis-rainbow-live-controls-* directory')
    if not output.is_dir() or (output/'live-manifest.json').exists():
        raise ValueError('Unique output directory required')
    old, shaders, repack, reflection, checks = build.dependencies()
    prepare, parser = old.prior()
    dxc = prepare.Dxc()
    known = repack.known_frames()

    def save(name,data):
        if (output/name).exists():
            if (output/name).read_bytes() != data:
                raise ValueError('Existing different artifact: '+name)
            return
        with (output/name).open('xb') as f:
            f.write(data)

    rows = []
    for info in repack.material_info():
        original = repack.material_original(info)
        _,_,off,size = repack.material_sections(original)
        before = repack.parse_shader(original[off:off+size],known)
        replacements, programs = [], []
        for index, label in enumerate(('first','second','third','fourth')):
            stem = info['material']+'-'+label
            data = before['programs'][index]['data']
            parts = {c['tag']:data[c['offset']+8:c['offset']+8+c['size']] for c in parser.dxbc(data)}
            save(stem+'-original-STAT.program',parts['STAT'])
            stat = reflection.dump(output/(stem+'-original-STAT.program')).decode()
            save(stem+'-original-STAT.ll.txt',stat.encode())
            text = old.sealed(old.J1/(stem+'.ll.txt'),old.J1).decode()
            module = live_shader.module_for(stem,text,stat,shaders,index==1,include_original)
            save(stem+'.input.ll',module.encode())
            assembled, message = dxc.operation(module.encode(),assemble=True)
            if message:
                raise ValueError(message)
            signed, message = dxc.operation(assembled,assemble=False)
            if message or signed[4:20] == bytes(16):
                raise ValueError('DXIL validation failed: '+str(message))
            save(stem+'.dxbc',signed)
            reflected = reflection.dump(output/(stem+'.dxbc')).decode()
            save(stem+'.ll.txt',reflected.encode())
            actual = shader_tables.reflection_descriptors(reflected,old.murmur64)['c_material_exports']
            for name, _, offset, width in live_shader.EXPORTS:
                fields = [field for field in actual if field['name']==name]
                if len(fields)!=1 or (fields[0]['offset'],fields[0]['width']) != (offset,width):
                    raise ValueError('Independent DXC custom export reflection')
            # Validate all original named field offsets as well as added fields.
            prior_fields = shader_tables.reflection_descriptors(text,old.murmur64)
            after_fields = shader_tables.reflection_descriptors(reflected,old.murmur64)
            for name,fields in prior_fields.items():
                expected = after_fields[name][:-2] if name=='c_material_exports' else after_fields[name]
                if fields != expected:
                    raise ValueError('Existing buffer field moved')
            def generic(t):
                return re.sub(r', !dx.controlflow.hints !\d+', '', t.replace('@vs_main','@ps_main'))
            def hints(t):
                ids = re.findall(r', !dx.controlflow.hints !(\d+)',t)
                return [re.search(r'^!'+key+r' = distinct !\{!'+key+r', !"dx.controlflow.hints", i32 ([12])\}',t,re.M)[1] for key in ids]
            if hints(module) != hints(reflected):
                raise ValueError('Executable control-flow hints changed')
            if build.canonical(generic(module),shaders) != build.canonical(generic(reflected),shaders):
                raise ValueError('Executable body changed during assembly')
            new_parts = {c['tag']:signed[c['offset']+8:c['offset']+8+c['size']] for c in parser.dxbc(signed)}
            for tag in ('SFI0','ISG1','OSG1','PSV0'):
                if parts[tag] != new_parts[tag]:
                    raise ValueError('Signature/binding chunk changed: '+tag)
            save(stem+'-STAT.program',new_parts['STAT'])
            new_stat = reflection.dump(output/(stem+'-STAT.program')).decode()
            save(stem+'-STAT.ll.txt',new_stat.encode())
            if checks.count_instructions(generic(reflected)) != checks.counters(new_stat):
                raise ValueError('STAT counter mismatch')
            replacements.append(signed)
            programs.append(dict(program=label,external_dxc_validation=True,
                                 executable_changed=index==1,custom_offsets=[80,96],
                                 original_offsets_preserved=True,sha256=clouds.sha(signed)))
        material,shader,report = export_resources.author(original,replacements,repack,old,parser,known)
        save(info['material']+'.material',material)
        save(info['material']+'.shader43',shader)
        rows.append(dict(material=info['material'],file=info['material']+'.material',
                         sha256=clouds.sha(material),original_sha256=clouds.sha(original),
                         source_reference=info['stream_reference'],programs=programs,**report))
    manifest = dict(status='EXPERIMENTAL OFFLINE LIVE EXPORTS; NATIVE REGISTRATION NOT TESTED',
                    targets=rows,required_particle=str(root/'cloud-rename-NOOP-OFFLINE-UNTESTED.bundle'),
                    texture_patch_required=False,installed=False,
                    rainbow_includes_original=include_original,
                    stock_ramp_required=include_original)
    save('live-manifest.json',(json.dumps(manifest,indent=2)+'\n').encode())
    print(json.dumps(manifest,indent=2))


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output',required=True)
    cli.add_argument('--include-original',action='store_true')
    args = cli.parse_args()
    run(args.output,args.include_original)
