"""Closed implementation package codec; recomputes all derived identities."""
from dataclasses import asdict, fields
from ordessa_infrastructure.encoding import canonical_bytes
from ..common.mechanisms.codec import (canonical_value,require_object,decode_tuple,
    decode_digest,decode_scope,decode_actor,decode_blob_ref)
from ..common.outcomes.diagnostics import ReferenceError
from ..artifacts.ref_codec import decode_artifact_ref
from ..artifacts.method_codec import decode_method_ref, decode_exact_method_resource
from ..artifacts.models import MethodContent
from ..artifacts.provenance_codec import decode_source
from ..changes.ref_codec import decode_proposal_ref
from ..changes.baseline_codec import decode_repository_ref
from ..changes.models import ChangeSet
from ..changes.codec import _template_ref, _env
from ..approvals.ref_codec import decode_approval_ref
from ..reviews.ref_codec import decode_review_ref
from .models import (ImplementationPackage,ImplementationPackagePayload,PreparedPackagePayload,
    PackageDocument,PackageFile,PackageCoverage,PackageDerivation,package_payload_projection)
from .refs import ImplementationPackageRef

_CODE='INVALID_PACKAGE'
def _object(value,cls):
    return require_object(value,{f.name for f in fields(cls)},_CODE)
def _tuple(value,decode):
    return decode_tuple(value,decode,_CODE)
def decode_package_ref(value):
    _object(value,ImplementationPackageRef)
    if value['kind'] != 'implementation_package':
        raise ReferenceError(_CODE)
    return ImplementationPackageRef(value['realm_id'],value['project_id'],value['package_id'],decode_digest(value['digest']))
def _file(value):
    _object(value,PackageFile)
    return PackageFile(value['repository_id'],value['path'],value['operation'],
        None if value['before_blob_digest'] is None else decode_digest(value['before_blob_digest']),
        value['rename_from'],_tuple(value['proposal_refs'],decode_proposal_ref),value['purpose'])
def _coverage(value):
    _object(value,PackageCoverage)
    return PackageCoverage(decode_proposal_ref(value['proposal_ref']),
        _tuple(value['instructions'],decode_blob_ref),_tuple(value['files'],lambda x:x),
        _tuple(value['acceptance_requirements'],_template_ref),_tuple(value['basis_refs'],decode_artifact_ref))
def _derivation(value):
    _object(value,PackageDerivation)
    return PackageDerivation(decode_digest(value['intent_digest']),_tuple(value['input_refs'],decode_blob_ref),
        value['generator_id'],value['generator_version'],decode_digest(value['output_manifest_digest']))
def _document(value):
    _object(value,PackageDocument)
    return PackageDocument(value['role'],decode_source(value['source_ref']))
def _content(value):
    if value is None:
        return None
    require_object(value,{'schema_ref','value','rendered_body_ref'},_CODE)
    return MethodContent.from_value(decode_exact_method_resource(value['schema_ref']),value['value'],
        None if value['rendered_body_ref'] is None else decode_blob_ref(value['rendered_body_ref']))
def decode_package_payload(value):
    if type(value) is not dict:
        raise ReferenceError(_CODE)
    if value.get('package_schema') == 'ordessa.implementation-package/v2':
        _object(value,PreparedPackagePayload)
        return PreparedPackagePayload(decode_source(value['baseline']),decode_source(value['candidate']),
            decode_proposal_ref(value['change_ref']),_tuple(value['review_refs'],decode_review_ref),
            decode_method_ref(value['method_ref']),_tuple(value['method_resource_refs'],decode_exact_method_resource),
            _tuple(value['documents'],_document))
    _object(value,ImplementationPackagePayload)
    if value['package_schema'] != 'ordessa.implementation-package/v1':
        raise ReferenceError(_CODE)
    change=value['change_set']
    require_object(change,{'proposal_refs','digest'},_CODE)
    cs=ChangeSet(_tuple(change['proposal_refs'],decode_proposal_ref))
    if cs.digest != decode_digest(change['digest']):
        raise ReferenceError(_CODE)
    return ImplementationPackagePayload(value['implementation_intent_id'],cs,
        _tuple(value['design_targets'],decode_artifact_ref),_tuple(value['authorization_refs'],decode_approval_ref),
        decode_method_ref(value['method_ref']),_tuple(value['required_review_refs'],decode_review_ref),
        _tuple(value['baseline_snapshots'],decode_repository_ref),_tuple(value['resolved_file_manifest'],_file),
        decode_blob_ref(value['instructions_ref']),_tuple(value['skill_snapshot_refs'],decode_exact_method_resource),
        _env(value['execution_profile_ref']),_tuple(value['allowed_actions'],lambda x:x),
        _tuple(value['acceptance_requirements'],_template_ref),_tuple(value['proposal_coverage'],_coverage),
        _content(value['method_content']),_derivation(value['derivation']))
def encode_package(record):
    if type(record) is not ImplementationPackage:
        raise ReferenceError(_CODE)
    value={'scope':asdict(record.scope),'package_id':record.package_id,'created_at':record.created_at,
        'created_by':asdict(record.created_by),'payload':package_payload_projection(record.payload),'digest':asdict(record.digest)}
    raw=canonical_bytes(value)
    if len(raw) > 2097152:
        raise ReferenceError('PACKAGE_BOUND_EXCEEDED')
    return raw
def decode_package(raw):
    try:
        value=canonical_value(raw)
        _object(value,ImplementationPackage)
        record=ImplementationPackage(decode_scope(value['scope']),value['package_id'],value['created_at'],
            decode_actor(value['created_by']),decode_package_payload(value['payload']))
        if record.digest != decode_digest(value['digest']) or encode_package(record) != raw:
            raise ReferenceError(_CODE)
        return record
    except (KeyError,TypeError,ValueError,AttributeError,RecursionError,OverflowError):
        raise ReferenceError(_CODE) from None
