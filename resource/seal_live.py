"""Seal the completed u1 offline evidence and exact implementation inputs."""
import ast
import json
from pathlib import Path

import build
import clouds
import verify_components


def run():
    root = clouds.DOCS/'analysis-rainbow-live-controls-20260918-u1'
    files = {'particle':root/'cloud-rename-NOOP-OFFLINE-UNTESTED.bundle',
             'a8':root/'live-v3/a8dc696a363ec3d3.material',
             '49':root/'live-v3/49697971309d8a04.material'}
    receipt = verify_components.verify(files)
    def save(name, obj):
        with (root/name).open('x',encoding='utf-8') as out:
            out.write(json.dumps(obj,indent=2)+'\n')
    inputs = {}
    mod = build.WORKSPACE/'mods/active/RainbowFlame'
    paths = list(mod.rglob('*'))
    paths += [build.WORKSPACE/p for p in (
        'types/darktide/rainbow_flame.lua','types/SOURCES.md','types/CONTRACTS.md',
        'docs/rainbow-flame-development-20260918.md',
        'darktide-source/scripts/components/particle_effect.lua',
        'darktide-source/scripts/settings/fx/effect_templates/yellow_stimmed.lua',
        'darktide-source/scripts/settings/equipment/weapon_templates/force_staffs/forcestaff_p2_m1.lua',
        'darktide-source/scripts/extension_systems/visual_loadout/wieldable_slot_scripts/flamer_gas_effects.lua',
        'darktide-source/scripts/extension_systems/visual_loadout/utilities/wieldable_slot_scripts.lua',
        'dmf-source/scripts/mods/dmf/modules/core/hooks.lua',
        'dmf-source/scripts/mods/dmf/modules/core/toggling.lua',
        'dmf-source/scripts/mods/dmf/modules/core/events.lua',
        'dmf-source/scripts/mods/dmf/modules/core/safe_calls.lua',
        'dmf-source/scripts/mods/dmf/modules/ui/options/mod_options.lua')]
    for path in paths:
        if not path.is_file():
            continue
        data = path.read_bytes()
        if path.suffix=='.py':
            ast.parse(data,filename=str(path))
        inputs[path.relative_to(build.WORKSPACE).as_posix()] = dict(size=len(data),sha256=clouds.sha(data))
    save('component-set-verification.json',receipt)
    save('final-inputs.json',inputs)
    save('preserved-evidence.json',dict(t1_manifest_sha256=clouds.sealed_tree(clouds.T1),
                                      e1_manifest_sha256=clouds.sealed_tree(clouds.E1)))
    inventory = {}
    for path in sorted(root.rglob('*')):
        if path.is_file():
            data = path.read_bytes()
            inventory[path.relative_to(root).as_posix()] = dict(size=len(data),sha256=clouds.sha(data))
    save('SHA256SUMS.json',inventory)
    print(json.dumps(dict(files=len(inventory),inputs=len(inputs),
                          manifest_sha256=clouds.sha((root/'SHA256SUMS.json').read_bytes()),
                          components=receipt),indent=2))


if __name__ == '__main__':
    run()
