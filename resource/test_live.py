"""Offline corruption, reflection and independently evaluated live-control tests."""
import colorsys
import copy
import json
import math
import random
import re
import struct
import unittest

import build
import clouds
import export_resources as er
import live_shader
import shader_tables as st
import verify_components
from test_build import f32

ROOT = build.WORKSPACE/'docs/analysis-rainbow-live-controls-20260918-u1'
CURRENT = build.WORKSPACE/'docs/analysis-rainbow-live-controls-20260921-opacity1'


def execute(fragment, rgb, time, hsv, cycle):
    values: dict[str,float] = dict(zip(('%r','%g','%b','%time'),map(f32,(*rgb,time))))
    buffers: dict[str,tuple[float,...]] = {}
    def value(token):
        if token.startswith('%'):
            return values[token]
        if token.startswith('0x'):
            return struct.unpack('>d',bytes.fromhex(token[2:]))[0]
        return float(token)
    for line in fragment.splitlines():
        name, op = line.strip().split(' = ')
        if '@dx.op.cbufferLoadLegacy' in op:
            buffers[name] = tuple(map(f32,hsv if 'i32 5)' in op else (*cycle,0,0)))
            continue
        elif op.startswith('extractvalue'):
            match = re.search(r' (%[\w.]+), (\d+)$',op)
            assert match is not None
            result = buffers[match[1]][int(match[2])]
        elif op.startswith('select'):
            match = re.fullmatch(r'select i1 (%[\w.]+), float ([^,]+), float (.+)',op)
            assert match is not None
            result = value(match[2] if values[match[1]] else match[3])
        elif op.startswith('fcmp'):
            match = re.fullmatch(r'fcmp (ogt|one) float ([^,]+), (.+)', op)
            assert match is not None
            a, b = value(match[2]), value(match[3])
            result = a > b if match[1] == 'ogt' else a != b
        elif op.startswith('call'):
            args = [value(t) for t in re.findall(r', float ([^,) ]+)',op)]
            opcode = re.search(r'i32 (\d+)',op)
            assert opcode is not None
            code = int(opcode[1])
            if code == 35: result = max(args)
            elif code == 22: result = args[0]-math.floor(args[0])
            elif code == 6: result = abs(args[0])
            elif code == 7: result = min(1,max(0,args[0]))
            else: raise AssertionError(op)
        else:
            code,args = op.split(' float ')
            a,b = map(value,args.split(', '))
            if code == 'fmul': result = a*b
            elif code == 'fadd': result = a+b
            elif code == 'fsub': result = a-b
            else: raise AssertionError(op)
        values[name] = f32(result)
    return tuple(values['%rf.'+c] for c in 'rgb')


class LiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old,cls.shaders,cls.repack,_,_ = build.dependencies()
        cls.checks,cls.fmt = clouds.dependencies()

    def test_cloud_scope_witnesses_and_roundtrip(self):
        bundle,raw,report = clouds.author()
        self.assertEqual(bundle,(ROOT/'cloud-rename-NOOP-OFFLINE-UNTESTED.bundle').read_bytes())
        self.assertEqual(raw,(ROOT/'psyker_flame_staff_code_control.particles').read_bytes())
        changes, witnesses = report['logical_changed_bytes'], report['witnesses']
        assert isinstance(changes,list) and isinstance(witnesses,list)
        self.assertEqual(len(changes),12)
        self.assertEqual(len(witnesses),4)
        self.assertEqual(sum(x['matching_descriptor_occurrences'] for x in self.checks.field_checks()),53)

    def test_cloud_corruptions_and_duplicate_reference(self):
        body = self.checks.r.load_body()
        for bad in (body[:-1],b'\0'*4+body[4:]):
            with self.assertRaises(ValueError): clouds.rename(bad,self.checks)
        duplicate = bytearray(body)
        struct.pack_into('<I',duplicate,500,clouds.OLD_IDS[0])
        with self.assertRaisesRegex(ValueError,'internal cloud reference'):
            clouds.rename(duplicate,self.checks)

    def test_all_table_roundtrips_and_corruptions(self):
        for info in self.repack.material_info():
            material = self.repack.material_original(info)
            mo,ms,so,ss = self.repack.material_sections(material)
            template = er.material_template(material[mo:mo+ms])
            self.assertEqual(er.serialize_material(template),material[mo:mo+ms])
            shader = material[so:so+ss]
            start,length = struct.unpack_from('<II',shader,32)
            raw = shader[start:start+length]
            model = st.parse(raw)
            self.assertEqual(st.serialize(model),raw)
            for bad in (raw[:-1],struct.pack('<I',2)+raw[4:],raw[:12]+b'\xff'*4+raw[16:]):
                with self.assertRaises(ValueError): st.parse(bad)
            for field in ('size','allocation_offset'):
                broken = copy.deepcopy(model)
                broken['buffers'][3][field] += 1
                with self.assertRaises(ValueError): st.serialize(broken)
            broken = copy.deepcopy(model)
            broken['buffers'][3]['descriptors'][-1][3] = 0x100000
            with self.assertRaises(ValueError): st.serialize(broken)

    def test_generated_exports_defaults_and_all_program_reflections(self):
        folder = CURRENT
        manifest = json.loads((folder/'live-manifest.json').read_text())
        for target,info in zip(manifest['targets'],self.repack.material_info()):
            data = (folder/target['file']).read_bytes()
            self.assertEqual(clouds.sha(data),target['sha256'])
            original = self.repack.material_original(info)
            mo,ms,so,ss = self.repack.material_sections(data)
            template = er.material_template(data[mo:mo+ms])
            omo,oms,_,_ = self.repack.material_sections(original)
            old_template = er.material_template(original[omo:omo+oms])
            for key in ('head','unknown1','textures','contexts','unknown2','unknown3'):
                self.assertEqual(template[key],old_template[key])
            self.assertEqual(template['descriptors'][:-2],old_template['descriptors'])
            self.assertEqual(template['values'][:-24],old_template['values'])
            self.assertEqual(template['values'][-24:],bytes(24))
            shader = data[so:so+ss]
            default = struct.unpack_from('<I',shader,20)[0]
            defaults = er.default_table(shader[default:])
            self.assertEqual([v for _,v in defaults[-2:]],[bytes(16),bytes(8)])
            broken = bytearray(shader[default:])
            struct.pack_into('<I',broken,16,0xffffffff)
            with self.assertRaises(ValueError): er.default_table(broken)
            for label in ('first','second','third','fourth'):
                stem = target['material']+'-'+label
                original_text = self.old.sealed(self.old.J1/(stem+'.ll.txt'),self.old.J1).decode()
                stat = (folder/(stem+'-original-STAT.ll.txt')).read_text()
                self.assertEqual(live_shader.module_for(stem,original_text,stat,self.shaders,label=='second',
                                                        manifest['rainbow_includes_original']),
                                  (folder/(stem+'.input.ll')).read_text())
                text = (folder/(target['material']+'-'+label+'.ll.txt')).read_text()
                fields = st.reflection_descriptors(text,self.old.murmur64)['c_material_exports']
                self.assertEqual([(f['name'],f['offset'],f['width']) for f in fields[-2:]],
                                 [(live_shader.HSV,80,16),(live_shader.CYCLE,96,8)])

    def test_live_ir_independent_color_opacity_oracle_and_stock(self):
        fragment = live_shader.instructions(('%r','%g','%b'),'%time',self.shaders)
        rng = random.Random(182026)
        cases = [(h,o,b,e,cycle,t) for h in (0,1/6,1/3,.5,2/3,5/6,1)
                 for o in (0,.35,1) for b in (0,1,2) for e in (-1,0,1)
                 for cycle in (0,1) for t in (0,1,4,8)]
        cases += [(rng.random(),rng.random(),2*rng.random(),1,1,rng.uniform(-20,20)) for _ in range(200)]
        for h,o,b,e,cycle,t in cases:
            rgb = tuple(rng.random() for _ in range(3))
            result = execute(fragment,rgb,t,(h,o,b,e),(cycle,.125))
            color = colorsys.hsv_to_rgb((t*.125 if cycle else h)%1,1,b*max(rgb)) if e > 0 else rgb
            expected = tuple(o*x for x in color) if e != 0 else rgb
            for a,v in zip(result,expected): self.assertAlmostEqual(a,v,delta=0.00001)
        for i in range(6):
            a = execute(fragment,(1,1,1),i/6*8,(.73,1,1,1),(1,.125))
            b = colorsys.hsv_to_rgb(i/6,1,1)
            for x,y in zip(a,b): self.assertAlmostEqual(x,y,delta=0.000002)

    def test_only_original_rgb_consumers_changed(self):
        for name in ('a8dc696a363ec3d3','49697971309d8a04'):
            original = self.old.sealed(self.old.J1/(name+'-second.ll.txt'),self.old.J1).decode()
            module = (CURRENT/(name+'-second.input.ll')).read_text()
            rgb,time,outputs = (('%152','%153','%154'),'%156',(190,191,192)) if name.startswith('a8') else (('%146','%147','%148'),'%150',(184,185,186))
            body = self.shaders.body(module).replace(live_shader.instructions(rgb,time,self.shaders,True),'')
            for channel,source,target,gain in zip('rgb',rgb,outputs,(7,8,9)):
                body = body.replace(f'%{target} = fmul fast float %rf.{channel}, %{gain}',f'%{target} = fmul fast float {source}, %{gain}')
            self.assertEqual(body,self.shaders.body(original))

    def test_component_set_rejects_partial_and_mixed_builds(self):
        current = build.WORKSPACE/'docs/analysis-rainbow-live-controls-20260919-e1'
        files = {'particle':current/'cloud-rename-NOOP-OFFLINE-UNTESTED.bundle',
                 'a8':current/'a8dc696a363ec3d3.material',
                 '49':current/'49697971309d8a04.material'}
        self.assertEqual(len(verify_components.verify(files)['files']),3)
        with self.assertRaisesRegex(ValueError,'All three'):
            verify_components.verify({'particle':files['particle']})
        for name in ('a8','49'):
            mixed = dict(files)
            mixed[name] = ROOT/'live-v2'/files[name].name
            with self.assertRaisesRegex(ValueError,'Resource set mismatch'):
                verify_components.verify(mixed)
        for prior in ('live-v3','live-v4'):
            mixed = dict(files)
            mixed['49'] = ROOT/prior/files['49'].name
            with self.assertRaisesRegex(ValueError,'Resource set mismatch'):
                verify_components.verify(mixed)

    def test_packed_layout_regression(self):
        import audit_live
        rows = audit_live.audit()
        self.assertEqual(len(rows),10)
        failures = [r for r in rows if not r['packed']]
        self.assertEqual([(r['build'],r['material']) for r in failures],
                         [('live-v3','49697971309d8a04')])

    def test_fine_phase_continuity(self):
        fragment = live_shader.instructions(('%r','%g','%b'),'%time',self.shaders)
        count = 12000
        samples = [execute(fragment,(1,1,1),8*i/count,(.73,.2,1,1),(1,.125))
                   for i in range(count+1)]
        self.assertEqual(len(set(samples[:-1])),count)
        bound = max(abs(a-b) for left,right in zip(samples,samples[1:])
                    for a,b in zip(left,right))
        self.assertLessEqual(bound,6/count+0.000003)
        self.assertEqual(samples[0],samples[-1])
        for boundary in range(7):
            phase = boundary/6
            left = execute(fragment,(1,1,1),8*(phase-1e-6),(.9,1,1,1),(1,.125))
            right = execute(fragment,(1,1,1),8*(phase+1e-6),(.1,1,1,1),(1,.125))
            self.assertLess(max(abs(a-b) for a,b in zip(left,right)),0.000015)
        print(f'Continuous float32 rainbow: {count} unique samples; max channel step {bound:.9f}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
