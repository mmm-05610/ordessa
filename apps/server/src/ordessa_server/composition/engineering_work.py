"""One exact configured work on the existing Engineering wire/runtime factory.

All arguments are trusted composition inputs from original owner outputs. No
JSON actor, plan, arbitrary SQL, live callable or implicit method selection is
accepted through this interface.
"""
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import Scope as EngineeringScope

from .engineering_admission import assemble_engineering_admission
from .engineering_business_bindings import OriginalProposalBindings
from .engineering_method_management import OriginalMethodManagement
from .engineering_reviewer_source import OriginalJevReviewerSource


def proposal_application_ports_factory(*, scope, proposal_ref, phases, policy_bytes,
        policy_ref, provider, evidence_reader, read_context, runs, roles, accepted_models, flows):
    """Bind a real selected Proposal and its actual JEV executions to original ports.

    Neither a bundle pin nor calling this function adopts a method. The trusted
    launcher must separately use the original issued internal methods.adopt
    context/CAS before starting this configured work. Missing original evidence
    or current explicit grants continues to refuse, including default Server.
    """
    def construct(factory, access, selected_scope):
        if selected_scope != scope:
            raise ApplicationError('SCOPE_MISMATCH')
        domain_scope = EngineeringScope(scope.realm_id, scope.project_id)
        snapshots = SQLiteSnapshotStore(factory.library)
        controls = SQLiteMethodControl(factory, snapshots)
        bindings = OriginalProposalBindings(factory, controls, scope=domain_scope,
            proposal_ref=proposal_ref, phases=phases)
        source = OriginalJevReviewerSource(access=access, scope=scope,
            blobs=SQLiteBlobStore(factory.library), evidence_reader=evidence_reader,
            read_context=read_context, provider=provider, runs=runs, roles=roles,
            accepted_models=accepted_models, flows=flows)
        return assemble_engineering_admission(factory, access, scope,
            management=OriginalMethodManagement(access, scope), bindings=bindings,
            reviewer_source=source, policy_bytes=policy_bytes, policy_ref=policy_ref).application_ports
    return construct
