"""The sole strict JSON/YAML resource parser; no file IO."""
from __future__ import annotations
import json
from copy import deepcopy
from functools import lru_cache
from typing import Any
import yaml
from yaml.events import (AliasEvent, MappingEndEvent, MappingStartEvent, ScalarEvent, SequenceEndEvent, SequenceStartEvent)
from ordessa_infrastructure.encoding import decode_json
from ..definitions.errors import MethodError, MethodFailure
from ..validation.values import validate_json_value

class _StrictLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            raise MethodFailure(MethodError("YAML_MERGE_KEY", "YAML merge keys are not supported"))
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise MethodFailure(MethodError("YAML_NON_STRING_KEY", "mapping keys must be strings"))
        if key in result:
            raise MethodFailure(MethodError("DUPLICATE_KEY", f"duplicate mapping key: {key}"))
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _reject_aliases_anchors(text: str, path: str, depth_limit: int) -> None:
    container_depth = 0
    try:
        for event in yaml.parse(text, Loader=_StrictLoader):
            if isinstance(event, AliasEvent) or getattr(event, "anchor", None) is not None:
                raise MethodFailure(MethodError("YAML_ALIAS_OR_ANCHOR", "YAML aliases and anchors are not supported", path=path))
            # Root values are depth zero, matching validate_json_value. Count
            # containers before construction, including the depth of leaves.
            if isinstance(event, (MappingStartEvent, SequenceStartEvent, ScalarEvent)):
                if container_depth > depth_limit:
                    raise MethodFailure(MethodError("STRUCTURE_TOO_DEEP", "resource exceeds the nesting limit", path=path))
            if isinstance(event, (MappingStartEvent, SequenceStartEvent)):
                container_depth += 1
            elif isinstance(event, (MappingEndEvent, SequenceEndEvent)):
                container_depth -= 1
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise MethodFailure(MethodError(
            "METHOD_PARSE_ERROR", "YAML could not be parsed", path=path,
            line=(mark.line + 1) if mark else None,
            column=(mark.column + 1) if mark else None,
        )) from exc


_PARSE_CACHE_MAX_BYTES = 256 * 1024


# Keep multiple resources across bundle reconstructions with a fixed bound.
# Only successful pure parsing is reused; resource IO and current request
# state remain outside this cache.
@lru_cache(maxsize=128)
def _parse_small_document(raw: bytes, media_type: str, path: str, depth_limit: int) -> Any:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise MethodFailure(MethodError("METHOD_ENCODING_ERROR", "resource must be UTF-8", path=path)) from exc
    try:
        if media_type in {"application/json", "application/schema+json"} or path.endswith(".json"):
            value = decode_json(text)
        elif media_type in {"application/yaml", "text/yaml", "application/x-yaml"} or path.endswith((".yaml", ".yml")):
            _reject_aliases_anchors(text, path, depth_limit)
            value = yaml.load(text, Loader=_StrictLoader)
        else:
            return text
    except MethodFailure:
        raise
    except RecursionError as exc:
        raise MethodFailure(MethodError(
            "STRUCTURE_TOO_DEEP", "resource exceeds the parser nesting limit", path=path,
        )) from exc
    except (yaml.YAMLError, ValueError, json.JSONDecodeError) as exc:
        mark = getattr(exc, "problem_mark", None)
        raise MethodFailure(MethodError(
            "METHOD_PARSE_ERROR", "resource could not be parsed", path=path,
            line=(mark.line + 1) if mark else None,
            column=(mark.column + 1) if mark else None,
        )) from exc
    validate_json_value(value, path=path, depth_limit=depth_limit)
    return value


def parse_document(raw: bytes, media_type: str, path: str, *, depth_limit: int = 64) -> Any:
    # Large captures bypass the cache so a small number of inputs cannot pin
    # an unbounded amount of source data or parsed trees in process memory.
    if len(raw) > _PARSE_CACHE_MAX_BYTES:
        return _parse_small_document.__wrapped__(raw, media_type, path, depth_limit)
    return deepcopy(_parse_small_document(raw, media_type, path, depth_limit))
