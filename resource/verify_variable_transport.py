"""Independent byte reconstruction and negative checks for the bounded s1 evidence."""
import ast
import importlib
import json
import struct
import sys
from inspect_variable_transport import ROOT, annotate, witness

OUT = ROOT / 'docs/analysis-rainbow-variable-bindings-20260919-s1'


def main():
    source = ROOT / 'docs/analysis-rainbow-global-soulblaze-deployment-20260919-m1/30ebeee18093c079.installed-before.rollback'
    data = source.read_bytes()
    assert witness.sha(data) == witness.bundle.STOCK_SHA
    bundle, blocks = witness.bundle.read(data, witness.bundle.baseline.decoder())
    assert witness.bundle.serialize(bundle, blocks) == data
    inventory = json.loads((OUT / 'inventory.json').read_text())
    by_id = {tuple(p['identity']): p for p in inventory['particles']}
    declarations = importlib.import_module('declarations')
    checked, gpu, variables, variable_gpu, systems = 0, 0, 0, 0, 0
    for record in witness.bundle.fmt.records(bundle):
        if record['identity'][0] != witness.r.murmur('particles'):
            continue
        raw = record['raw']
        p = annotate(raw)
        retained = by_id[record['identity']]
        assert p['sha256'] == retained['sha256']
        prefix = raw[:82 + p['variable_count'] * 16]
        rebuilt = prefix + b''.join(struct.pack('<144I', *r['prefix_words']) +
                    b''.join(bytes.fromhex(x) for x in r['sections_hex']) for r in p['records'])
        assert rebuilt == raw
        _, names, defaults, _ = declarations.split(raw)
        assert declarations.rebuild(raw, names, defaults) == raw
        local_gpu = sum(r['kind'] == 4 for r in p['records'])
        gpu += local_gpu
        variables += bool(p['variable_count'])
        variable_gpu += bool(p['variable_count'] and local_gpu)
        checked += 1
        systems += len(p['records'])
    assert checked == 76 and not inventory['rejected']
    original = (ROOT / inventory['controls'][0]['path']).read_bytes()
    rejected = 0
    for offset, replacement in ((74, 0xffffffff), (78, 0xffffffff),
                                 (38 + 44 + 134*4, 0xffffffff),
                                 (38 + 44 + 143*4, 0xffffffff),
                                 (29, 1), (38, 103)):
        invalid = bytearray(original)
        struct.pack_into('<I', invalid, offset, replacement)
        try:
            annotate(invalid)
        except (ValueError, struct.error, AssertionError):
            rejected += 1
        else:
            raise AssertionError('Accepted malformed field')
    profile = json.loads((OUT / 'section-profile.json').read_text())
    assert len(profile['gpu']) == gpu + 5
    assert all(p['initializer_count'] == p['initializer_bytes'] == 0 for p in profile['gpu'])
    radius = inventory['controls'][-1]
    third = annotate((OUT / '3p_force_staff_explosion_indicator.particles').read_bytes())
    assert json.loads(json.dumps(third['variables'])) == radius['variables']
    prefix_differences = [(4*i, a, b) for i, (a, b) in enumerate(zip(
        radius['records'][3]['prefix_words'], third['records'][3]['prefix_words'])) if a != b]
    section_differences = [i for i, (a, b) in enumerate(zip(
        radius['records'][3]['sections_hex'], third['records'][3]['sections_hex'])) if a != b]
    section_byte_differences = {}
    for i in section_differences:
        a = bytes.fromhex(radius['records'][3]['sections_hex'][i])
        b = bytes.fromhex(third['records'][3]['sections_hex'][i])
        assert len(a) == len(b)
        section_byte_differences[i] = [(j, x, y) for j, (x, y) in enumerate(zip(a, b)) if x != y]
    materials = json.loads((OUT / 'new-reflection.json').read_text())
    programs = 0
    for material in materials:
        assert witness.sha((OUT / (material['id'] + '.material')).read_bytes()) == material['sha256']
        for i, program in enumerate(material.get('programs', [])):
            path = OUT / material['id'] / f'program-{i:02d}.dxbc'
            assert witness.sha(path.read_bytes()) == program['sha256'] and program['dxc_valid']
            assert path.with_suffix('.ll.txt').is_file()
            programs += 1
    assert programs == 40
    scripts = [ROOT / 'mods/active/RainbowFlame/resource' / (name + '.py') for name in (
        'inspect_variable_transport', 'compare_variable_transport', 'inspect_variable_components',
        'profile_variable_sections', 'reflect_variable_transport', 'verify_variable_transport')]
    for path in scripts:
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    source_files = [ROOT / 'darktide-source/scripts' / p for p in (
        'components/valkyrie_gameplay.lua',
        'settings/equipment/weapon_templates/force_staffs/forcestaff_p1_m1.lua',
        'extension_systems/visual_loadout/wieldable_slot_scripts/force_staff_aoe_targeting_effects.lua',
        'extension_systems/fx/player_unit_fx_extension.lua',
        'utilities/expeditions/expedition_event_templates.lua')]
    result = dict(resources=711, particle_roundtrips=checked, systems=systems,
                  gpu_systems=gpu, effects_with_variables=variables,
                  effects_with_variables_and_gpu=variable_gpu,
                  malformed_field_rejections=rejected, new_dxc_validated_programs=programs,
                  first_third_person_gpu_prefix_differences=prefix_differences,
                  first_third_person_gpu_section_differences=section_byte_differences,
                  python_syntax_files=len(scripts), installed_writes=0,
                  source_sha256={str(p.relative_to(ROOT)): witness.sha(p.read_bytes()) for p in source_files},
                  implementation_status='No dynamic candidate; native property transport not established')
    text = json.dumps(result, indent=2) + '\n'
    report_path = OUT / 'validation.json'
    if report_path.exists():
        assert report_path.read_text(encoding='utf-8') == text
    else:
        with report_path.open('x', encoding='utf-8') as file:
            file.write(text)
    if '--seal' in sys.argv[1:]:
        paths = sorted(p for p in OUT.rglob('*') if p.is_file() and p.name != 'SHA256SUMS.json')
        paths += scripts + [ROOT / 'mods/active/RainbowFlame/README.md', ROOT / 'types/CONTRACTS.md']
        manifest = {str(p.relative_to(ROOT)): witness.sha(p.read_bytes()) for p in paths}
        with (OUT / 'SHA256SUMS.json').open('x', encoding='utf-8') as file:
            json.dump(manifest, file, indent=2)
            file.write('\n')
        assert all(witness.sha((ROOT / p).read_bytes()) == h for p, h in manifest.items())
        print('Sealed files:', len(manifest))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
