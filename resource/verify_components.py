"""Read-only preactivation check of the original-inclusive e1 staff resource set.

Does not install, enable Lua, connect to a game, or attest bundle precedence/cache.
Use only with the exact candidate receipt and coordinated deployment paths.
"""
import argparse
import hashlib
import json
from pathlib import Path

EXPECTED = {
    'particle': 'a5d76ad745cb65bc29f628a11f90c4891d60ee88e4938a0bb3b8f62b0fcd0911',
    'a8': 'f14191c3fa372d10089fac9d8e042d9363e33929aa551b57e02b79ffe51585fb',
    '49': '5634cbbc75b5953260b03727c0ad09b045ce32e1ba553d9e14256c8b4275f9a8',
}


def verify(files):
    if set(files) != set(EXPECTED):
        raise ValueError('All three components are required')
    result = []
    for name, path in files.items():
        path = Path(path).resolve()
        if not path.is_file() or path.stat().st_size > 2*1024*1024:
            raise ValueError('Missing/oversize resource: '+name)
        data = path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != EXPECTED[name]:
            raise ValueError('Resource set mismatch: '+name+'; keep live controller inactive')
        result.append(dict(component=name,path=str(path),size=len(data),sha256=actual))
    return dict(status='EXACT THREE-FILE CANDIDATE MATCH; NOT A LOADED-RESOURCE ATTESTATION',files=result)


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--particle',required=True)
    cli.add_argument('--a8',required=True)
    cli.add_argument('--49',dest='material49',required=True)
    args = cli.parse_args()
    print(json.dumps(verify({'particle':args.particle,'a8':args.a8,'49':args.material49}),indent=2))
