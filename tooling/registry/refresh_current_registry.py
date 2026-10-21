"""One explicit current-job registry transition, 126 -> 127.

R1's 101 -> 102 tool and byte locks are independent historical artifacts. This
planner accepts the genuine 126 bytes, the complete current source facts and the
one reviewed command-contract change. Writing stays disabled until the final
source freeze supplies EXPECTED_TARGET_SHA256; no later drift can repin 127.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

BASE_SHA256 = 'c8808cd2eaeded69737ac40ffabc41b171dd581b112e1fd150306829b5d5d1f7'
BASE_REVISION = 126
TARGET_REVISION = 127
EXPECTED_TARGET_SHA256 = '0e9ee0dea78a9df4e48a74d4d4e40caca1aaf77c62b5cde5d94028ae7bb10fac'
ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'packages/engineering/src/ordessa_engineering'
RESOURCE = SOURCE / 'adapters/registry/resources/operation_registry.v1.json'
BASE_FIXTURE = ROOT / 'packages/engineering/tests/fixtures/current-registry/operation_registry.v1.r126.json'


class RefreshRefused(RuntimeError):
    pass


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode()


def current_operations():
    from ordessa_engineering.application.api.service import EngineeringService
    return {item.capability_id: {'version':item.interface_version,
        'inputs':item.contract['input_schema'], 'results':item.contract['workflow_outcomes']}
        for item in EngineeringService.operation_capabilities().capabilities}


def _reviewed_operations(base):
    from ordessa_engineering.application.usecases.reviews.assignments import ASSIGN_REVIEWER, command_input_schema
    operations = json.loads(json.dumps(base['operations']))
    operations[ASSIGN_REVIEWER] = {**operations[ASSIGN_REVIEWER],
        'version':'2', 'inputs':command_input_schema(ASSIGN_REVIEWER)}
    return operations


def build_plan(*, old_bytes, facts, operations):
    from ordessa_engineering.adapters.registry import source_integrity as si
    from ordessa_engineering.domain.artifacts.library_material_codec import content_digest
    from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
    base_bytes = BASE_FIXTURE.read_bytes()
    if _hash(base_bytes) != BASE_SHA256:
        raise RefreshRefused('recorded revision-126 base bytes differ')
    base = json.loads(base_bytes)
    if base['revision'] != BASE_REVISION:
        raise RefreshRefused('base revision differs')
    for value in (base, json.loads(old_bytes)):
        if (value['implementation_digest'] != content_digest(value['implementation'])
                or value['registry_digest'] != content_digest({k:v for k,v in value.items() if k!='registry_digest'})):
            raise RefreshRefused('input registry content digest differs')
    if operations != _reviewed_operations(base):
        raise RefreshRefused('unreviewed operation contract change')
    if (facts.get('ordessa_decision_version') != '0.2.0'
            or facts.get('decision_contract_version') != 'decision-job/1'
            or facts.get('jsonschema_version') != '4.20.0'
            or facts.get('referencing_version') != '0.36.2'
            or 'pydantic_graph_version' in facts):
        raise RefreshRefused('current dependency facts differ from the reviewed job closure')
    try:
        si.verify_implementation({'implementation':facts})
    except EngineeringError as error:
        raise RefreshRefused('candidate facts differ from the complete actual source closure') from error
    candidate = {**base, 'revision':TARGET_REVISION, 'operations':operations, 'implementation':facts}
    candidate['implementation_digest'] = content_digest(facts)
    candidate['registry_digest'] = content_digest({k:v for k,v in candidate.items() if k!='registry_digest'})
    raw = _encoded(candidate)
    if EXPECTED_TARGET_SHA256 is not None and _hash(raw) != EXPECTED_TARGET_SHA256:
        raise RefreshRefused('candidate bytes differ from the frozen revision-127 target')
    if old_bytes == raw:
        return None
    if _hash(old_bytes) != BASE_SHA256:
        raise RefreshRefused('input is neither exact revision-126 base nor current frozen target')
    previous = base['implementation']['engineering']
    current = facts['engineering']
    return {'bytes':raw, 'receipt':{
        'before_revision':BASE_REVISION, 'after_revision':TARGET_REVISION,
        'before_sha256':BASE_SHA256, 'after_sha256':_hash(raw),
        'implementation_digest':candidate['implementation_digest'], 'registry_digest':candidate['registry_digest'],
        'source_added':sorted(set(current)-set(previous)), 'source_removed':sorted(set(previous)-set(current)),
        'source_changed':{key:{'before':previous[key], 'after':current[key]}
                          for key in sorted(set(previous)&set(current)) if previous[key]!=current[key]},
        'changed_operations':{key:{'before':base['operations'][key], 'after':operations[key]}
                              for key in operations if operations[key]!=base['operations'][key]},
        'foreign_before':{k:v for k,v in base['implementation'].items() if k!='engineering'},
        'foreign_after':{k:v for k,v in facts.items() if k!='engineering'},
        'runtime_source_keys':list(facts['ordessa_decision']),
    }}


def _atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name+'.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args(argv)
    from ordessa_engineering.adapters.registry import source_integrity as si
    if Path(si.__file__).resolve() != SOURCE/'adapters/registry/source_integrity.py':
        raise RefreshRefused('refresh requires the selected checkout source; wheels are verified by load_registry')
    before = RESOURCE.read_bytes()
    facts = si.implementation_facts()
    operations = current_operations()
    plan = build_plan(old_bytes=before, facts=facts, operations=operations)
    if plan is None:
        print('unchanged: exact current target')
        return 0
    if not args.write:
        print(json.dumps(plan['receipt'], indent=2, sort_keys=True))
        return 0
    if EXPECTED_TARGET_SHA256 is None or args.evidence is None:
        raise RefreshRefused('writing requires frozen target hash and an explicit evidence directory')
    if RESOURCE.read_bytes()!=before or si.implementation_facts()!=facts or current_operations()!=operations:
        raise RefreshRefused('source/resource/contracts changed after planning; no writes')
    _atomic(args.evidence/'operation_registry.v1.r126.json', before)
    _atomic(RESOURCE, plan['bytes'])
    _atomic(args.evidence/'RECEIPT.json', _encoded(plan['receipt']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
