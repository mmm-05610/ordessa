"""Captured method/material bindings on domain records, not methods-stage objects.

MaterialBudget retains its explicit conversion to the methods snapshot owner.
This pure value contract imports no methods stage and owns no method authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import NewType
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.common.models.values import Digest, RelativePath, validate_id, normalized_path
MethodId = NewType("MethodId", str)

@dataclass(frozen=True)
class MethodRef:
    method_id: MethodId
    release_version: str
    schema_version: int
    snapshot_digest: Digest

    def __post_init__(self):
        validate_id(self.method_id)
        validate_id(self.release_version)
        if type(self.schema_version) is not int or self.schema_version < 1 or type(self.snapshot_digest) is not Digest:
            raise ReferenceError("INVALID_SCHEMA")

@dataclass(frozen=True)
class ExactMethodResourceRef:
    method_ref: MethodRef
    logical_path: RelativePath
    resource_digest: Digest
    resource_id: str

    def __post_init__(self):
        try:
            validate_id(self.resource_id)
        except ReferenceError:
            raise ReferenceError('INVALID_METHOD_RESOURCE') from None
        normalized_path(self.logical_path)
        if type(self.method_ref) is not MethodRef or type(self.resource_digest) is not Digest:
            raise ReferenceError('INVALID_METHOD_RESOURCE')
