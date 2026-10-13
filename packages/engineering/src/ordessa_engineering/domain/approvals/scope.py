"""Closed action bounds. String containment is not filesystem attestation."""
from dataclasses import dataclass

from ..common.models.values import (Digest, validate_id)
from ..common.outcomes.diagnostics import (ReferenceError)
from ..common.models.values import (normalized_path)
from ..common.models.values import (validate_items, ordered_unique)
from ordessa_infrastructure.encoding import canonical_bytes
from dataclasses import asdict

ACTIONS = frozenset({'accept_artifact', 'apply_change', 'generate_package',
    'edit_repository', 'run_checks', 'create_local_commit', 'export_bundle',
    'publish_branch', 'deploy'})
FILE_OPERATIONS = frozenset({'add', 'modify', 'delete', 'rename'})


@dataclass(frozen=True)
class PathRule:
    root: str
    match: str
    operations: tuple[str, ...]

    def __post_init__(self):
        normalized_path(self.root)
        if type(self.match) is not str or self.match not in {'exact', 'subtree'}:
            raise ReferenceError('INVALID_ACTION_SCOPE')
        validate_items(self.operations, str, nonempty=True)
        if any(op not in FILE_OPERATIONS for op in self.operations):
            raise ReferenceError('INVALID_ACTION_SCOPE')
        object.__setattr__(self, 'operations', ordered_unique(self.operations, lambda x:x, code='DUPLICATE_CHECK'))

    def contains(self, path, operation):
        normalized_path(path)
        return operation in self.operations and (path == self.root or
            self.match == 'subtree' and path.startswith(self.root + '/'))


@dataclass(frozen=True)
class RepositoryScope:
    repository_id: str
    path_rules: tuple[PathRule, ...]

    def __post_init__(self):
        validate_id(self.repository_id)
        validate_items(self.path_rules, PathRule, nonempty=True)
        object.__setattr__(self, 'path_rules', ordered_unique(self.path_rules, lambda x:canonical_bytes(asdict(x)), code='DUPLICATE_CHECK'))


@dataclass(frozen=True)
class EnvironmentRef:
    environment_id: str
    profile_id: str
    profile_digest: Digest

    def __post_init__(self):
        validate_id(self.environment_id)
        validate_id(self.profile_id)
        if type(self.profile_digest) is not Digest:
            raise ReferenceError('INVALID_ACTION_SCOPE')


@dataclass(frozen=True)
class EffectLimit:
    action: str
    target_id: str
    constraint_digest: Digest

    def __post_init__(self):
        if type(self.action) is not str or self.action not in ACTIONS:
            raise ReferenceError('INVALID_ACTION_SCOPE')
        validate_id(self.target_id)
        if type(self.constraint_digest) is not Digest:
            raise ReferenceError('INVALID_ACTION_SCOPE')


@dataclass(frozen=True)
class ActionScope:
    project_id: str
    repository_scopes: tuple[RepositoryScope, ...]
    environment_refs: tuple[EnvironmentRef, ...]
    effect_limits: tuple[EffectLimit, ...]
    exclusions: tuple[PathRule, ...]
    implementation_intent_id: str

    def __post_init__(self):
        validate_id(self.project_id)
        validate_id(self.implementation_intent_id)
        for name, kind, key in (
            ('repository_scopes', RepositoryScope, lambda x:x.repository_id),
            ('environment_refs', EnvironmentRef, lambda x:x.environment_id),
            ('effect_limits', EffectLimit, lambda x:(x.action,x.target_id)),
            ('exclusions', PathRule, lambda x:canonical_bytes(asdict(x)))):
            value=getattr(self,name)
            validate_items(value,kind)
            object.__setattr__(self,name,ordered_unique(value,key, code='DUPLICATE_CHECK'))

    def allows_path(self, repository_id, path, operation, *, destination=None):
        if type(operation) is not str or operation not in FILE_OPERATIONS:
            raise ReferenceError('INVALID_ACTION_SCOPE')
        normalized_path(path)
        if operation == 'rename':
            if destination is None:
                raise ReferenceError('INVALID_ACTION_SCOPE')
            normalized_path(destination)
            paths=(path,destination)
        elif destination is not None:
            raise ReferenceError('INVALID_ACTION_SCOPE')
        else:
            paths=(path,)
        rules=next((r.path_rules for r in self.repository_scopes if r.repository_id==repository_id),())
        return all(not any(r.contains(p,operation) for r in self.exclusions)
                   and any(r.contains(p,operation) for r in rules) for p in paths)
