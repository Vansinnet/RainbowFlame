"""Retained candidate, corruption, all32 preservation and float32 color oracles."""
import argparse
import colorsys
import copy
import io
import json
import math
from pathlib import Path
import re
import struct
import sys
import unittest

sys.dont_write_bytecode = True
import build
import export_resources as exports
import shader_tables as tables
import staff84_live as author
import surface_tables
from test_live import execute


class Staff84Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = author.SOURCE.read_bytes()
        cls.child_original = author.CHILD_SOURCE.read_bytes()
        cls.shader = author.inspect(cls.original)
        cls.material = (author.OUTPUT/(author.PARENT+'.material')).read_bytes()
        cls.child = (author.OUTPUT/(author.CHILD+'.material')).read_bytes()
        cls.new_shader = (author.OUTPUT/(author.PARENT+'.shader43')).read_bytes()
        cls.report = json.loads((author.OUTPUT/'report.json').read_text())
        cls.programs = next(r for r in json.loads((author.LAYERS/'reflection.json').read_text()) if r['material'] == author.PARENT)['programs']
        cls.old,cls.shaders,cls.repack,_,cls.checks = build.dependencies()
        cls.text = (author.LAYERS/author.PARENT/'program-01.ll.txt').read_text()
        module = (author.OUTPUT/'program-01.input.ll').read_text()
        cls.fragment = '\n'.join(line for line in module.splitlines() if line.startswith(('  %rf.','  %hc.')))+'\n'
        for old,new in ((150,'r'),(151,'g'),(152,'b'),(154,'time')):
            cls.fragment = re.sub(r'%'+str(old)+r'(?!\d)','%'+new,cls.fragment)
        loads = [line for line in cls.fragment.splitlines() if '@dx.op.cbufferLoadLegacy' in line]
        if len(loads) != 2 or not loads[0].endswith('Handle %4, i32 5)') or not loads[1].endswith('Handle %4, i32 6)'):
            raise AssertionError('Actual HSV/cycle register addresses')

    @staticmethod
    def model(data):
        _,mo,ms,*_ = struct.unpack_from('<7I',data)
        return exports.material_template(data[mo:mo+ms])

    def hash32(self,name):
        return self.old.murmur64(name.encode()) >> 32

    def replacements(self):
        return {i:(author.OUTPUT/f'program-{i:02d}.dxbc').read_bytes() for i in author.TARGETS}

    def test_manifest_and_new_python_syntax(self):
        manifest = json.loads((author.OUTPUT/'SHA256SUMS.json').read_text())
        for name,expected in manifest.items():
            self.assertEqual(Path(name).name,name)
            self.assertEqual(author.identity((author.OUTPUT/name).read_bytes()),expected,name)
        for name in ('staff84_live.py','test_staff84_live.py'):
            p = Path(__file__).with_name(name)
            compile(p.read_bytes(),str(p),'exec')

    def test_retained_parent_noop_every_section(self):
        _,mo,ms,so,ss,tail,ts = struct.unpack_from('<7I',self.original)
        start,length,ds,dl = struct.unpack_from('<4I',self.shader,32)
        default = struct.unpack_from('<I',self.shader,20)[0]
        registration = author.serialize_groups(author.groups_for(self.shader[start:start+length]))
        device,cursor = bytearray(),ds
        for p in self.programs:
            begin,end = p['frame']
            metadata = surface_tables.metadata(self.shader,end)
            serialized = tables.words(metadata['header'])+b''.join(tables.table(t['rows']) for t in metadata['tables'])
            self.assertEqual(serialized,self.shader[end:metadata['span'][1]])
            device += self.shader[cursor:begin-8]+tables.words([1,end-begin])+self.shader[begin:end]+serialized
            cursor = metadata['span'][1]
        device += self.shader[cursor:ds+dl]
        defaults = exports.serialize_defaults(exports.default_table(self.shader[default:]))
        rebuilt = self.shader[:start]+registration+self.shader[start+length:ds]+device+self.shader[ds+dl:default]+defaults
        rebuilt += bytes(ss-len(rebuilt))
        self.assertEqual(self.original[:28]+exports.serialize_material(self.model(self.original))+rebuilt+self.original[tail:tail+ts],self.original)

    def test_deterministic_rebuild_and_whole_parent_child_reverse(self):
        material,shader,report = author.material_for(self.original,self.programs,self.replacements(),self.old,self.repack)
        self.assertEqual(material,self.material)
        self.assertEqual(shader,self.new_shader)
        self.assertTrue(report['byte_exact_reverse'])
        self.assertEqual(author.child_for(self.child_original,self.hash32),self.child)

    def test_child_inheritance_textures_values_and_absence_sentinels(self):
        version,mo,ms,so,ss,tail,ts = struct.unpack_from('<7I',self.child)
        self.assertEqual((version,mo,ms,so,ss,tail,ts),(61,28,336,0xffffffff,0,0xffffffff,0))
        self.assertEqual(mo+ms,len(self.child))
        old,new = self.model(self.child_original),self.model(self.child)
        for key in old:
            if key not in ('values','descriptors'):
                self.assertEqual(old[key],new[key],key)
        self.assertEqual(new['descriptors'][:-2],old['descriptors'])
        self.assertEqual(new['values'][:-24],old['values'])
        self.assertEqual(new['values'][-24:],bytes(24))
        self.assertEqual([d[3:] for d in new['descriptors'][-2:]],[[52,16],[68,8]])
        self.assertEqual(struct.unpack_from('<IQQ',exports.serialize_material(new)),(0,int(author.PARENT,16),0))
        self.assertEqual([(channel,lo | hi<<32) for channel,lo,hi in new['textures']],
                         [(0x424651bc,0x23d3373664c5b0e1),(0xc46564d3,0xd516f85947af4619)])

    def test_parent_exports_native_allocations_and_zero_defaults(self):
        old,new = self.model(self.original),self.model(self.material)
        for key in old:
            if key not in ('values','descriptors'):
                self.assertEqual(old[key],new[key],key)
        self.assertEqual(new['descriptors'][:-2],old['descriptors'])
        self.assertEqual(new['values'][:-24],old['values'])
        self.assertEqual(new['values'][-24:],bytes(24))
        self.assertEqual([d[3:] for d in new['descriptors'][-2:]],[[36,16],[52,8]])
        start,length = struct.unpack_from('<2I',self.new_shader,32)
        groups = author.groups_for(self.new_shader[start:start+length],True)
        os,ol = struct.unpack_from('<2I',self.shader,32)
        stock = author.groups_for(self.shader[os:os+ol])
        for g,b in zip(groups,stock,strict=True):
            expected = copy.deepcopy(b)
            expected['allocation'] = 384
            expected['buffers'][3]['size'] = 112
            expected['buffers'][3]['descriptors'] += [[kind,0,self.hash32(name),offset,width] for name,kind,offset,width in author.EXPORTS]
            self.assertEqual(g,expected)
        default = struct.unpack_from('<I',self.new_shader,20)[0]
        od = struct.unpack_from('<I',self.shader,20)[0]
        defaults = exports.default_table(self.new_shader[default:])
        self.assertEqual(defaults[:-2],exports.default_table(self.shader[od:]))
        self.assertEqual(defaults[-2:],[(self.hash32(author.EXPORTS[0][0]),bytes(16)),(self.hash32(author.EXPORTS[1][0]),bytes(8))])

    def test_all32_frames_and_every_metadata_table(self):
        frames = self.report['verification']['frames']
        self.assertEqual(len(frames),32)
        self.assertEqual(len(self.report['programs']),32)
        for i,(stock,new) in enumerate(zip(self.programs,frames,strict=True)):
            a,b = stock['frame']
            x,y = new['frame']
            data = (author.OUTPUT/f'program-{i:02d}.dxbc').read_bytes()
            before,after = surface_tables.metadata(self.shader,b),surface_tables.metadata(self.new_shader,y)
            self.assertEqual(after['header'][1],len(data))
            self.assertEqual(after['header'][2] | after['header'][3]<<32,self.old.murmur64(self.new_shader[x:y]))
            if i not in author.TARGETS:
                self.assertEqual(self.shader[a:b],self.new_shader[x:y])
                self.assertEqual(data,(author.LAYERS/author.PARENT/f'program-{i:02d}.dxbc').read_bytes())
                self.assertEqual((author.OUTPUT/f'program-{i:02d}.ll.txt').read_text(),(author.LAYERS/author.PARENT/f'program-{i:02d}.ll.txt').read_text())
            else:
                self.assertEqual(self.repack.frame_payload(self.new_shader[x:y],len(data),{}),data)
            self.assertTrue(self.report['programs'][i]['signed_validation'])
            self.assertTrue(self.report['programs'][i]['reflection_readback'])
            for t,(bt,nt) in enumerate(zip(before['tables'],after['tables'],strict=True)):
                rows = copy.deepcopy(bt['rows'])
                if t == 0:
                    for row in rows:
                        if row[0] == self.hash32('c_material_exports'):
                            row[2] = 112
                self.assertEqual(rows,nt['rows'],(i,t))

    def test_eight_signed_reflections_and_stat_counters(self):
        for i in author.TARGETS:
            before = (author.LAYERS/author.PARENT/f'program-{i:02d}.ll.txt').read_text()
            after = (author.OUTPUT/f'program-{i:02d}.ll.txt').read_text()
            module = (author.OUTPUT/f'program-{i:02d}.input.ll').read_text()
            stat = (author.OUTPUT/f'program-{i:02d}-STAT.ll.txt').read_text()
            author.verify_buffer_definitions(before,after)
            self.assertEqual(build.canonical(module,self.shaders),build.canonical(after,self.shaders))
            self.assertEqual(self.checks.count_instructions(after),self.checks.counters(stat))
            with self.assertRaises(ValueError):
                author.verify_buffer_definitions(before,after.replace('Offset:  416','Offset:  432'))
            with self.assertRaises(ValueError):
                author.verify_buffer_definitions(before,after.replace('Offset:   80','Offset:   84'))

    def test_only_three_ramp_operands_change(self):
        for i in author.TARGETS:
            stock = (author.LAYERS/author.PARENT/f'program-{i:02d}.ll.txt').read_text()
            module = (author.OUTPUT/f'program-{i:02d}.input.ll').read_text()
            body = self.shaders.body(module)
            body = '\n'.join(line for line in body.splitlines() if not line.startswith(('  %rf.','  %hc.')))
            for channel,source,target,gain in zip('rgb',(150,151,152),(193,197,201),(192,196,200)):
                body = body.replace(f'%{target} = fmul fast float %{gain}, %rf.{channel}',f'%{target} = fmul fast float %{gain}, %{source}')
            self.assertEqual(body,self.shaders.body(stock))

    def test_corrupt_registration_and_source_rejected(self):
        start,length = struct.unpack_from('<2I',self.shader,32)
        raw = self.shader[start:start+length]
        for bad in (raw[:-1],tables.words([4])+raw[4:],raw[:12]+b'\xff'*4+raw[16:]):
            with self.assertRaises(ValueError):
                author.groups_for(bad)
        groups = author.groups_for(raw)
        for key in ('size','allocation_offset'):
            bad = copy.deepcopy(groups)
            bad[0]['buffers'][3][key] += 16
            with self.assertRaises(ValueError):
                author.groups_for(author.serialize_groups(bad))
        bad = copy.deepcopy(groups)
        bad[0]['buffers'][3]['descriptors'][-1][3] = 80
        with self.assertRaisesRegex(ValueError,'Descriptor extent'):
            author.groups_for(author.serialize_groups(bad))
        with self.assertRaisesRegex(ValueError,'parent identity'):
            author.inspect(self.original[:-1]+bytes([self.original[-1]^1]))
        with self.assertRaisesRegex(ValueError,'child identity'):
            author.child_for(self.child_original[:-1]+bytes([self.child_original[-1]^1]),self.hash32)

    def test_wrong_sample_uv_binding_consumer_rejected(self):
        for old,new in [('Handle %69, %dx.types.Handle %50','Handle %54, %dx.types.Handle %50'),
                        ('float %143, float %143','float %10, float %11'),
                        ('%193 = fmul fast float %192, %150','%193 = fmul fast float %196, %150'),
                        ('%67 = extractvalue %dx.types.CBufRet.i32 %66, 2','%67 = extractvalue %dx.types.CBufRet.i32 %66, 0'),
                        ('i8 2, i32 1, i32 1, i1 false','i8 2, i32 2, i32 2, i1 false')]:
            self.assertIn(old,self.text)
            with self.assertRaises(ValueError):
                author.color_path(self.text.replace(old,new))

    def test_wrong_replacement_profile_and_template_collision_rejected(self):
        replacement = self.replacements()
        del replacement[29]
        with self.assertRaisesRegex(ValueError,'replacement profile'):
            author.material_for(self.original,self.programs,replacement,self.old,self.repack)
        model = self.model(self.child_original)
        model['descriptors'].append([3,0,self.hash32(author.EXPORTS[0][0]),0,16])
        with self.assertRaisesRegex(ValueError,'collision'):
            author.append_template(model,self.hash32,52)

    def test_zero_enable_stock_even_with_nonzero_other_controls(self):
        for rgb in ((0,0,0),(.125,.5,1),(2,.125,.75)):
            for time in (-10,0,5,123):
                for hsv in ((0,0,0,0),(1,0,2,0),(.5,1,0,0)):
                    for cycle in ((0,0),(1,.125)):
                        self.assertEqual(execute(self.fragment,rgb,time,hsv,cycle),rgb)

    def test_original_opacity_ignores_hue_brightness_cycle(self):
        rgb = (.125,.5,1)
        for opacity in (0,.25,1):
            for brightness in (0,.5,2):
                for cycle in (0,1):
                    self.assertEqual(execute(self.fragment,rgb,5,(.37,opacity,brightness,-1),(cycle,.125)),tuple(opacity*x for x in rgb))

    def test_custom_hue_value_brightness_opacity_oracle(self):
        for rgb in ((0,0,0),(.125,.5,1),(2,.125,.75)):
            for degree in range(0,361,5):
                for brightness,opacity in ((0,1),(1,.25),(2,1)):
                    expected = colorsys.hsv_to_rgb(degree/360,1,max(rgb)*brightness*opacity)
                    actual = execute(self.fragment,rgb,123,(degree/360,opacity,brightness,1),(0,.125))
                    for a,b in zip(actual,expected):
                        self.assertAlmostEqual(a,b,delta=8e-6)

    def test_rainbow_speed_original_pause_continuity_oracle(self):
        rgb = (.125,.5,1)
        for speed in (.125,1):
            for i in range(-100,1101):
                phase = i/1000
                p = phase-math.floor(phase)
                if p < .5:
                    hue,weight = p/.75,0
                elif p <= .75:
                    hue = 2/3
                    t = 1-abs(p-.625)*8
                    weight = t*t*(3-2*t)
                else:
                    hue,weight = (p-.25)/.75,0
                wheel = colorsys.hsv_to_rgb(hue,1,1)
                expected = tuple(.75*(a*(1-weight)+b*weight) for a,b in zip(wheel,rgb))
                actual = execute(self.fragment,rgb,phase/speed,(.93,.5,1.5,1),(1,speed))
                for a,b in zip(actual,expected):
                    self.assertAlmostEqual(a,b,delta=4e-6)


def main(evidence):
    if Path(evidence).name != evidence or not evidence.endswith('.json'):
        raise ValueError('New evidence JSON basename required')
    if not author.OUTPUT.is_dir() or (author.OUTPUT/evidence).exists() or (author.OUTPUT/'COMPLETE-SHA256SUMS.json').exists():
        raise ValueError('Completed candidate and unused evidence name required')
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Staff84Tests))
    print(stream.getvalue())
    record = dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                  successful=result.wasSuccessful(),log=stream.getvalue(),
                  sources={name:author.identity(Path(__file__).with_name(name).read_bytes()) for name in ('staff84_live.py','test_staff84_live.py')})
    with (author.OUTPUT/evidence).open('x',encoding='utf-8') as file:
        file.write(json.dumps(record,indent=2)+'\n')
    if not result.wasSuccessful():
        raise SystemExit(1)
    artifacts = {p.name:author.identity(p.read_bytes()) for p in sorted(author.OUTPUT.iterdir()) if p.is_file()}
    seal = dict(artifacts=artifacts,sources=record['sources'],successful_test_evidence=evidence,
                artifact_count=len(artifacts),artifact_bytes=sum(int(p['size']) for p in artifacts.values()))
    with (author.OUTPUT/'COMPLETE-SHA256SUMS.json').open('x',encoding='utf-8') as file:
        file.write(json.dumps(seal,indent=2)+'\n')


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--evidence',default='test-evidence.json')
    main(cli.parse_args().evidence)
