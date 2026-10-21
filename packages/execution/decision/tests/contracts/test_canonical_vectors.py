"""Canonical decision-json/1 golden over the packaged vectors (all of them)."""
from __future__ import annotations

import json
from importlib.resources import files

from ordessa_decision import canonical, digest


def test_all_packaged_vectors_canonical_and_digest():
    raw = files('ordessa_decision').joinpath('definitions', 'vectors.json').read_text(encoding='utf-8')
    vectors = json.loads(raw)
    assert len(vectors) == 5, 'the packaged vector set must not shrink'
    names = {v['name'] for v in vectors}
    assert names == {'request', 'proposal', 'descriptor', 'runmanifest', 'result'}
    for vector in vectors:
        value = json.loads(vector['canonical'])
        assert canonical(value) == vector['canonical'].encode('utf-8'), vector['name']
        assert digest(vector['name'], value) == vector['digest'], vector['name']
