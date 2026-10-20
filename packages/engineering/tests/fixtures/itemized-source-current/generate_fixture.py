"""Explicit caller-authored fixture revision; never run automatically by tests.

Retains original 20261014 inputs. Captures only the changed controlled helper;
this is synthetic test input, not a new review or product authority.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[4]
OLD = ROOT/'docs/implementation/packages-convergence-20261012/engineering/real-source-chain-20261014/itemized-review'
HELPER = 'packages/engineering/tests/application/test_real_source_chain.py'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    assert args.revision == 'itemized-current-job-fixture-v2'
    manifest = json.loads((OLD/'INPUT-MANIFEST.json').read_text())
    caller = json.loads((OLD/'materials/caller-review-input.json').read_text())
    raw = (ROOT/HELPER).read_bytes(); text = raw.decode()
    old_pin = dict(manifest['workspace_captures'][HELPER])
    pin = manifest['workspace_captures'][HELPER]
    pin.update(sha256=sha256(raw).hexdigest(), byte_length=len(raw), upstream_version=args.revision)
    for check in caller['checks']:
        for evidence in check['evidence']:
            ref = evidence['source_ref']
            if ref['source_id'] != 'service-fixture-capture':
                continue
            ref['capture']['upstream_version'] = args.revision
            ref['capture']['content_digest']['hex'] = pin['sha256']
            ref['byte_length'] = len(raw)
            if evidence['excerpt'] not in text:
                assert check['check_id'] == 'unique-record-authority'
                start = text.index('    library = EngineeringLibrary.create(')
                end = text.index('    with controls.guard(', start)
                evidence['excerpt'] = text[start:end].rstrip('\n')
            assert evidence['excerpt'] in text
    body = (json.dumps(caller,indent=2)+'\n').encode()
    manifest['materials']['materials/caller-review-input.json'] = {'sha256':sha256(body).hexdigest(),'byte_length':len(body)}
    manifest['fixture_revision'] = args.revision
    manifest['caller_material_revision'] = args.revision
    manifest['provenance'] = {'original_manifest_sha256':sha256((OLD/'INPUT-MANIFEST.json').read_bytes()).hexdigest(),
        'superseded_helper_capture':old_pin,
        'qualification':'Explicit synthetic caller-authored current-job test fixture; not original20261014 review evidence'}
    (HERE/'caller-review-input.json').write_bytes(body)
    (HERE/'INPUT-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__ == '__main__':
    main()
