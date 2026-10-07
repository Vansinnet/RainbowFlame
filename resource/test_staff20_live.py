"""Retained-artifact, corruption and independent float32 live-color tests."""
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
import shader_tables
import staff20_live as author
import staff20_live_preflight as preflight
import surface_tables
from test_live import execute

OUTPUT = preflight.ANALYSIS/'live20-offline-20260921-b1'


class Staff20Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = (preflight.LAYERS/(preflight.TARGET+'.material')).read_bytes()
        cls.audit,cls.shader = preflight.inspect(cls.original)
        cls.material = (OUTPUT/(preflight.TARGET+'.material')).read_bytes()
        cls.new_shader = (OUTPUT/(preflight.TARGET+'.shader43')).read_bytes()
        cls.manifest = json.loads((OUTPUT/'report.json').read_text())
        cls.programs = next(r for r in json.loads((preflight.LAYERS/'reflection.json').read_text()) if r['material'] == preflight.TARGET)['programs']
        cls.old,cls.shaders,cls.repack,_,_ = build.dependencies()
        cls.original_text = (preflight.LAYERS/preflight.TARGET/'program-01.ll.txt').read_text()
        cls.module = (OUTPUT/'program-01.input.ll').read_text()
        cls.fragment = '\n'.join(line for line in cls.module.splitlines() if line.startswith(('  %rf.','  %hc.')))+'\n'
        cls.fragment = re.sub(r'%152(?!\d)','%r',cls.fragment)
        cls.fragment = re.sub(r'%153(?!\d)','%g',cls.fragment)
        cls.fragment = re.sub(r'%154(?!\d)','%b',cls.fragment)
        cls.fragment = re.sub(r'%156(?!\d)','%time',cls.fragment)
        # The existing interpreter addresses its two inputs at registers 5/6.
        # Verify the actual emitted register addresses before adapting that interface.
        loads = [line for line in cls.fragment.splitlines() if '@dx.op.cbufferLoadLegacy' in line]
        if len(loads) != 2 or not loads[0].endswith('i32 7)') or not loads[1].endswith('i32 8)'):
            raise AssertionError('Authored control register addresses')
        cls.fragment = cls.fragment.replace('i32 7)','i32 5)').replace('i32 8)','i32 6)')

    def test_manifest_and_python_syntax(self):
        manifest = json.loads((OUTPUT/'SHA256SUMS.json').read_text())
        for name,expected in manifest.items():
            self.assertEqual(preflight.identity((OUTPUT/name).read_bytes()),expected,name)
        for name in ('staff20_live.py','staff20_live_preflight.py','test_staff20_live.py'):
            path = Path(__file__).with_name(name)
            compile(path.read_bytes(),str(path),'exec')

    def test_retained_noop_all_sections(self):
        _,mo,ms,so,ss,tail,ts = struct.unpack_from('<7I',self.original)
        template = exports.serialize_material(exports.material_template(self.original[mo:mo+ms]))
        start,length,ds,dl = struct.unpack_from('<4I',self.shader,32)
        default = struct.unpack_from('<I',self.shader,20)[0]
        tables = author.serialize_groups(author.groups_for(self.shader[start:start+length]))
        device,cursor = bytearray(),ds
        for p in self.programs:
            begin,end = p['frame']
            meta = surface_tables.metadata(self.shader,end)
            metadata = shader_tables.words(meta['header'])
            for table in meta['tables']:
                metadata += shader_tables.table(table['rows'])
            self.assertEqual(metadata,self.shader[end:meta['span'][1]])
            device += self.shader[cursor:begin-8]+shader_tables.words([1,end-begin])+self.shader[begin:end]+metadata
            cursor = meta['span'][1]
        device += self.shader[cursor:ds+dl]
        defaults = exports.serialize_defaults(exports.default_table(self.shader[default:]))
        shader = self.shader[:start]+tables+self.shader[start+length:ds]+device+self.shader[ds+dl:default]+defaults
        shader += bytes(ss-len(shader))
        self.assertEqual(self.original[:28]+template+shader+self.original[tail:tail+ts],self.original)

    def test_complete_material_rebuild_and_reverse(self):
        replacements = {i:(OUTPUT/f'program-{i:02d}.dxbc').read_bytes() for i in author.TARGETS}
        material,shader,report = author.material_for(self.original,self.programs,replacements,self.old,self.repack)
        self.assertEqual(material,self.material)
        self.assertEqual(shader,self.new_shader)
        self.assertTrue(report['byte_exact_reverse'])

    def test_custom_fields_defaults_and_original_offsets(self):
        _,mo,ms,so,ss,tail,ts = struct.unpack_from('<7I',self.material)
        self.assertEqual(self.material[so:so+ss],self.new_shader)
        self.assertEqual(tail+ts,len(self.material))
        model = exports.material_template(self.material[mo:mo+ms])
        old_model = exports.material_template(self.original[28:448])
        for key in ('head','unknown1','textures','contexts','unknown2','unknown3'):
            self.assertEqual(model[key],old_model[key])
        self.assertEqual(model['descriptors'][:-2],old_model['descriptors'])
        self.assertEqual(model['values'][:-24],old_model['values'])
        self.assertEqual(model['values'][-24:],bytes(24))
        start,length = struct.unpack_from('<2I',self.new_shader,32)
        groups = preflight.group_probe(self.new_shader[start:start+length])
        os,ol = struct.unpack_from('<2I',self.shader,32)
        old_groups = author.groups_for(self.shader[os:os+ol])
        for group,stock in zip(groups,old_groups,strict=True):
            self.assertEqual(group['allocation'],432)
            self.assertEqual(group['buffers'][3]['size'],144)
            self.assertEqual(group['buffers'][3]['descriptors'][:-2],stock['buffers'][3]['descriptors'])
            self.assertEqual([d[3:] for d in group['buffers'][3]['descriptors'][-2:]],[[112,16],[128,8]])
        default = struct.unpack_from('<I',self.new_shader,20)[0]
        self.assertEqual([v for _,v in exports.default_table(self.new_shader[default:])[-2:]],[bytes(16),bytes(8)])

    def test_every_non_target_frame_and_metadata(self):
        for i,(before,after) in enumerate(zip(self.programs,self.manifest['verification']['frames'],strict=True)):
            a,b = before['frame']
            x,y = after['frame']
            if i not in author.TARGETS:
                self.assertEqual(self.shader[a:b],self.new_shader[x:y])
            old = surface_tables.metadata(self.shader,b)
            new = surface_tables.metadata(self.new_shader,y)
            data = (preflight.LAYERS/preflight.TARGET/f'program-{i:02d}.dxbc').read_bytes()
            self.assertEqual(old['header'][1],len(data))
            text = (preflight.LAYERS/preflight.TARGET/f'program-{i:02d}.ll.txt').read_text()
            self.assertRegex(text,r';\s*\} c_material_exports;\s*; Offset:\s*0 Size:\s*104')
            for t,(ot,nt) in enumerate(zip(old['tables'],new['tables'],strict=True)):
                rows = copy.deepcopy(ot['rows'])
                if t == 0:
                    for row in rows:
                        if row[0] == self.old.murmur64(b'c_material_exports') >> 32:
                            row[2] = 144
                self.assertEqual(rows,nt['rows'])

    def test_complete_reflection_including_matrices_and_arrays(self):
        for i in author.TARGETS:
            before = (preflight.LAYERS/preflight.TARGET/f'program-{i:02d}.ll.txt').read_text()
            after = (OUTPUT/f'program-{i:02d}.ll.txt').read_text()
            author.verify_buffer_definitions(before,after)
            with self.assertRaises(ValueError):
                author.verify_buffer_definitions(before,after.replace('Offset:  416','Offset:  432'))

    def test_wrong_replacement_set_rejected(self):
        replacements = {i:(OUTPUT/f'program-{i:02d}.dxbc').read_bytes() for i in author.TARGETS}
        del replacements[13]
        with self.assertRaisesRegex(ValueError,'replacement profile'):
            author.material_for(self.original,self.programs,replacements,self.old,self.repack)

    def test_corrupt_layouts_and_identity_rejected(self):
        start,length = struct.unpack_from('<2I',self.shader,32)
        raw = self.shader[start:start+length]
        for bad in (raw[:-1],shader_tables.words([8])+raw[4:],raw[:12]+b'\xff'*4+raw[16:]):
            with self.assertRaises(ValueError):
                author.groups_for(bad)
        groups = author.groups_for(raw)
        for field in ('size','allocation_offset'):
            broken = copy.deepcopy(groups)
            broken[0]['buffers'][3][field] += 16
            with self.assertRaises(ValueError):
                author.groups_for(author.serialize_groups(broken))
        broken = copy.deepcopy(groups)
        broken[0]['buffers'][3]['descriptors'][-1][3] = 112
        with self.assertRaisesRegex(ValueError,'Descriptor extent'):
            author.groups_for(author.serialize_groups(broken))
        with self.assertRaisesRegex(ValueError,'identity'):
            preflight.inspect(self.original[:-1]+b'\x01')

    def test_wrong_sample_or_shape_path_rejected(self):
        for old,new in [('Handle %70, %dx.types.Handle %51','Handle %55, %dx.types.Handle %51'),
                        ('float %144, float %144','float %11, float %12'),
                        ('%190 = fmul fast float %152, %7','%190 = fmul fast float %152, %8'),
                        ('%68 = extractvalue %dx.types.CBufRet.i32 %67, 2','%68 = extractvalue %dx.types.CBufRet.i32 %67, 0')]:
            self.assertIn(old,self.original_text)
            with self.assertRaises(ValueError):
                author.color_path(self.original_text.replace(old,new))

    def test_only_three_stock_rgb_consumers_change(self):
        for i in author.TARGETS:
            text = (preflight.LAYERS/preflight.TARGET/f'program-{i:02d}.ll.txt').read_text()
            module = (OUTPUT/f'program-{i:02d}.input.ll').read_text()
            body = self.shaders.body(module)
            body = '\n'.join(line for line in body.splitlines() if not line.startswith(('  %rf.','  %hc.')))
            for channel,source,target,tint in zip('rgb',(152,153,154),(190,191,192),(7,8,9)):
                body = body.replace(f'%{target} = fmul fast float %rf.{channel}, %{tint}',f'%{target} = fmul fast float %{source}, %{tint}')
            self.assertEqual(body,self.shaders.body(text))

    def test_zero_default_restores_stock(self):
        for rgb in ((0,0,0),(.125,.5,1),(2,.125,.75)):
            for time in (-10,0,5,123):
                for controls in ((0,0,0,0),(1,0,2,0),(.5,1,0,0)):
                    self.assertEqual(execute(self.fragment,rgb,time,controls,(1,.125)),rgb)
                self.assertEqual(execute(self.fragment,rgb,time,(0,0,0,0),(0,0)),rgb)

    def test_original_rgb_opacity_brightness_independent(self):
        rgb = (.125,.5,1)
        for opacity in (0,.25,1):
            for brightness in (0,.5,2):
                for cycle in (0,1):
                    self.assertEqual(execute(self.fragment,rgb,5,(.37,opacity,brightness,-1),(cycle,.125)),tuple(opacity*x for x in rgb))

    def test_selected_hue_brightness_opacity_oracle(self):
        for degree in range(361):
            for brightness,opacity in ((0,1),(1,.25),(2,1)):
                expected = colorsys.hsv_to_rgb(degree/360,1,brightness*opacity)
                actual = execute(self.fragment,(.125,.5,1),123,(degree/360,opacity,brightness,1),(0,.125))
                for a,b in zip(actual,expected):
                    self.assertAlmostEqual(a,b,delta=4e-6)

    def test_rainbow_smooth_original_pause_and_speed_oracle(self):
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


def main(output,evidence_name):
    global OUTPUT
    OUTPUT = Path(output).resolve()
    if OUTPUT.parent != preflight.ANALYSIS or not OUTPUT.is_dir():
        raise ValueError('Existing target output directory required')
    if Path(evidence_name).name != evidence_name or not evidence_name.endswith('.json'):
        raise ValueError('Evidence must be a new JSON filename')
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Staff20Tests))
    print(stream.getvalue())
    evidence = dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                    successful=result.wasSuccessful(),log=stream.getvalue())
    with (OUTPUT/evidence_name).open('x',encoding='utf-8') as file:
        file.write(json.dumps(evidence,indent=2)+'\n')
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output',required=True)
    cli.add_argument('--evidence',default='test-evidence.json')
    args = cli.parse_args()
    main(args.output,args.evidence)
