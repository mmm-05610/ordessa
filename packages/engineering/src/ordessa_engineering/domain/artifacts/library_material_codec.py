from __future__ import annotations
import hashlib
from typing import Any, Mapping
from ordessa_infrastructure.encoding.canonical_json import canonical_text, CanonicalJSONError, LIBRARY_JSON_PROFILE
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from .library_materials import MaterialRef

def canonical_json(value: Any) -> str:
    try:
        return canonical_text(value, profile=LIBRARY_JSON_PROFILE)
    except CanonicalJSONError as exc:
        code = 'json_encode' if exc.stage == 'encode' else {'depth': 'json_depth', 'non_finite': 'json_non_finite', 'key_type': 'json_key_type', 'type': 'json_type'}[exc.reason]
        raise EngineeringError(code) from exc

def content_digest(value: Any) -> str:
    return 'sha256:' + hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()

def material_ref_to_dict(ref: MaterialRef) -> dict[str, Any]:
    return {'library_id': ref.library_id, 'kind': ref.kind, 'stable_id': ref.stable_id, 'revision': ref.revision, 'digest': ref.digest}

def material_ref_from_dict(value: Mapping[str, Any]) -> MaterialRef:
    if not isinstance(value, Mapping) or set(value) != {'library_id', 'kind', 'stable_id', 'revision', 'digest'}:
        raise EngineeringError('ref_shape')
    return MaterialRef(**dict(value))
