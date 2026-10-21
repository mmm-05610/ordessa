"""Offline schema admission and command validation, independent of owner code."""
from __future__ import annotations

import copy
from importlib.resources import files
import json

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource
from referencing.jsonschema import DRAFT202012


class ContractError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _deny_retrieval(uri: str):
    raise NoSuchResource(ref=uri)


def _references(value):
    if isinstance(value, dict):
        for keyword in ("$ref", "$dynamicRef"):
            if keyword in value:
                yield value[keyword]
        for child in value.values():
            yield from _references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child)


class ContractRegistry:
    def __init__(self):
        directory = files(__package__).joinpath("schemas")
        self._schemas = {p.name: json.loads(p.read_text()) for p in directory.iterdir()
                         if p.name.endswith(".schema.json")}
        self._catalog = json.loads(directory.joinpath("operation-catalog.json").read_text())
        self._methods = {item["operation"]: item for item in self._catalog["methods"]}
        self._resources = {schema["$id"]: schema for schema in self._schemas.values()}
        self._enabled = frozenset()
        for schema in self._resources.values():
            Draft202012Validator.check_schema(schema)

    @property
    def candidates(self) -> tuple[str, ...]:
        return tuple(sorted(self._methods))

    def bind(self, owner: str, schema: dict) -> None:
        identity = schema.get("$id")
        expected = {item[key] for item in self._methods.values() if item["owner"] == owner
                    for key in ("input_schema_ref", "output_schema_ref")}
        if identity not in expected or identity in self._resources:
            raise ContractError("OWNER_SCHEMA_BINDING_INVALID")
        Draft202012Validator.check_schema(schema)
        self._resources[identity] = copy.deepcopy(schema)
        self._enabled = frozenset()

    def freeze(self, operations: tuple[str, ...]) -> None:
        self._enabled = frozenset()
        if not operations or len(set(operations)) != len(operations):
            raise ContractError("INVALID_OPERATION_SET")
        pending = []
        for operation in operations:
            if operation not in self._methods:
                raise ContractError("UNKNOWN_OPERATION")
            item = self._methods[operation]
            pending.extend(item[key] for key in ("input_schema_ref", "output_schema_ref"))
        registry = Registry(retrieve=_deny_retrieval).with_resources(
            (uri, Resource.from_contents(schema)) for uri, schema in self._resources.items())
        queue = []
        for uri in pending:
            if uri not in self._resources:
                raise ContractError("OWNER_SCHEMA_MISSING")
            queue.append((registry.resolver(uri), Resource.from_contents(self._resources[uri])))
        seen = set()
        while queue:
            resolver, resource = queue.pop()
            schema = resource.contents
            if id(schema) in seen:
                continue
            seen.add(id(schema))
            references = [schema[key] for key in ("$ref", "$dynamicRef") if isinstance(schema, dict) and key in schema]
            for reference in references:
                try:
                    resolved = resolver.lookup(reference)
                except Exception as exc:
                    raise ContractError("SCHEMA_REFERENCE_UNRESOLVED") from exc
                queue.append((resolved.resolver, Resource.from_contents(resolved.contents,
                                                                        default_specification=DRAFT202012)))
            for child in resource.subresources():
                queue.append((resolver.in_subresource(child), child))
        self._enabled = frozenset(operations)

    def validate(self, schema_name: str, value: object) -> None:
        if schema_name not in self._schemas:
            raise ContractError("UNKNOWN_SCHEMA")
        registry = Registry(retrieve=_deny_retrieval).with_resources(
            (uri, Resource.from_contents(schema)) for uri, schema in self._resources.items())
        validator = Draft202012Validator(self._schemas[schema_name], registry=registry,
                                         format_checker=FormatChecker())
        try:
            if any(validator.iter_errors(value)):
                raise ContractError("SCHEMA_VALIDATION_FAILED")
        except ContractError:
            raise
        except Exception as exc:
            raise ContractError("SCHEMA_REFERENCE_UNRESOLVED") from exc

    def validate_command(self, value: dict) -> None:
        if value.get("operation") not in self._enabled:
            raise ContractError("OPERATION_UNAVAILABLE")
        self.validate("command-envelope.schema.json", value)
        seen = set()
        for precondition in value["preconditions"]:
            identity = (precondition["resource"]["kind"], precondition["resource"]["id"])
            if identity in seen:
                raise ContractError("DUPLICATE_PRECONDITION")
            seen.add(identity)
        scope = value["scope"]

        def inspect(item):
            if isinstance(item, dict):
                if "realm_id" in item and "project_id" in item and any(item[k] != scope[k] for k in scope):
                    raise ContractError("REF_SCOPE_MISMATCH")
                for child in item.values():
                    inspect(child)
            elif isinstance(item, list):
                for child in item:
                    inspect(child)

        inspect(value["parameters"])
