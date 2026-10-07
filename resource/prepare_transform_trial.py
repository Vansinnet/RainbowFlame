"""Freeze the three-file candidate and rollback plan. No installed paths are read or written."""
import json
from pathlib import Path

import transform_surface as author
import diagnostic_surface as ds

ROOT, OUT = author.ROOT, author.OUT


def pin(path):
    data = path.read_bytes()
    return dict(path=str(path), sha256=ds.sha(data), size=len(data))


def main():
    q1 = ROOT / 'docs/analysis-rainbow-surface-magenta-20260919-q1'
    previous_path = q1 / 'deployment-plan.json'
    seal = json.loads((q1 / 'SHA256SUMS.json').read_text())
    assert pin(previous_path)['sha256'] == seal['artifacts']['deployment-plan.json']['sha256']
    prior = json.loads(previous_path.read_text())
    manifest = json.loads((OUT / 'candidate-v2/candidate.json').read_text())
    tests = json.loads((OUT / 'shader-tests-v2.json').read_text())
    assert tests['exact_staff_output_matches'] == 11846 and tests['original_module_recoveries'] == 4
    lua_target, = [p for p in prior['preserved'] if p['path'].endswith('\\RainbowFlame.lua')]
    child_target, = [p for p in prior['preserved'] if p['sha256'] == manifest['child']['baseline_sha256']]
    assert prior['target']['sha256'] == manifest['parent']['baseline_sha256']
    baseline = OUT / 'RainbowFlame.before-transform.lua.reference'
    assert pin(baseline)['sha256'] == lua_target['sha256']
    frozen_lua = OUT / 'candidate-v2/RainbowFlame.v2.lua.candidate'
    ds.save(frozen_lua.parent, frozen_lua.name, author.RUNTIME.read_bytes())
    rows = []
    for name, target, candidate in (
            ('enemy-parent', prior['target'], OUT / 'candidate-v2' / author.PARENT),
            ('enemy-child-marker', child_target, OUT / 'candidate-v2' / author.CHILD),
            ('controller', lua_target, frozen_lua)):
        rows.append(dict(component=name, target=target, candidate=pin(candidate)))
    replaced = {r['target']['path'] for r in rows}
    result = dict(status='OFFLINE THREE-FILE PLAN; NOT INSTALLED; NO INSTALLED BACKUPS CREATED',
                  files=rows, preserved=[p for p in prior['preserved'] if p['path'] not in replaced],
                  historical_baseline=prior['baseline'], historical_links=prior['links'],
                  historical_plan=pin(previous_path),
                  rollback='At separately approved closed-game installation, freshly back up all three current targets with metadata and SHA-256 before any replacement. Restore all three exact backups, retaining m1/h1/k1; never substitute stock.',
                  execution='Use the reviewed f2 multi-file guarded transaction; this helper has no installation mode.',
                  gates=['fresh closed-game check before and during writes', 'all target and preserved hashes match',
                         'fresh build/database and link/ownership checks match historical baseline',
                         'candidate and active controller hashes match; preserve ACL/attributes/timestamps',
                         'unique protected rollback set; restore on partial failure'],
                  context='No current build, PID, process state or live visual observation is asserted')
    ds.save(OUT, 'deployment-plan-v2.json', (json.dumps(result, indent=2)+'\n').encode())
    print(json.dumps(dict(files=rows, installed_reads=0, installed_writes=0), indent=2))


if __name__ == '__main__':
    main()
