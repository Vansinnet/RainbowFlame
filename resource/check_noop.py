"""Independently extract the offline cloud no-op with the sealed limn tool."""
import json
from pathlib import Path
import struct
import subprocess

import clouds


def run():
    _, fmt = clouds.dependencies()
    root = clouds.DOCS/'analysis-rainbow-live-controls-20260918-u1'
    provenance = json.loads((clouds.E1/'provenance.json').read_text())
    tool = next(row for row in provenance['tools'] if row['path'].endswith('limn.exe'))
    executable = Path(tool['path'])
    if clouds.sha(executable.read_bytes()) != tool['sha256']:
        raise ValueError('Independent extractor identity changed')
    src = root/'cloud-rename-NOOP-OFFLINE-UNTESTED.bundle'
    dst = root/'independent-noop-extraction'
    if dst.exists():
        raise ValueError('Independent output already exists')
    command = [str(executable),'-i',str(src),'--dict',str(clouds.E1/'identities.txt'),
               '--dump-raw','-j','1','-o',str(dst),'*']
    completed = subprocess.run(command,capture_output=True,text=True,check=True,timeout=60)
    actual = {}
    for path in dst.rglob('*'):
        if path.is_file():
            data = path.read_bytes()
            key = struct.unpack_from('<QQ',data)
            if key in actual:
                raise ValueError('Duplicate independently extracted identity')
            actual[key] = data
    expected = {row['identity'][:2]:row['raw'] for row in fmt.records(fmt.read(src.read_bytes()))}
    if actual != expected or len(actual)!=19:
        raise ValueError('Independent extraction disagrees')
    report = dict(resources=19,all_bytes_match=True,tool_sha256=tool['sha256'],
                  command=command,stdout=completed.stdout,stderr=completed.stderr)
    with (root/'independent-noop-validation.json').open('x',encoding='utf-8') as f:
        f.write(json.dumps(report,indent=2)+'\n')
    print('Independent limn extraction: 19/19 resources byte-identical to bounded reader')


if __name__ == '__main__':
    run()
