"""Read-only current owner projections in the explicit historical observation format.

Historical DTOs describe evidence only. No old graph, UnitServices, admission
registry or configuration runtime is imported or assembled by this binding.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Mapping

from ordessa_agents.profiles import (
    ProfileService, decode_revision_ref, encode_content, encode_profile, encode_revision_ref,
)
from ordessa_agents.harness.providers.catalog import HarnessCatalog
from ordessa_units.configuration.proposal_input import OwnerProposalInput
from ordessa_decision.historical.context import ReadContext
from ordessa_decision.historical.values import ContractError, freeze, plain, digest, name
from ordessa_decision.historical.models import (
    ExternalRef, VersionedObservation, ObservationBatch, ObligationResult,
    ValidationReceipt, validate_ready,
)


@dataclass(frozen=True)
class ObservationQuery:
    kind: str
    parameters: Mapping

    def __post_init__(self):
        if self.kind not in ('providers', 'profiles', 'profile', 'nodes', 'configuration', 'configuration_offers'):
            raise ContractError('query_unregistered')
        if not isinstance(self.parameters, Mapping):
            raise ContractError('query_parameters')
        object.__setattr__(self, 'parameters', freeze(self.parameters))


@dataclass(frozen=True)
class ReadOwners:
    """Explicit current owner selection, without an implicit UnitServices facade.

    The host supplies the read context and original Profile admission. A Harness
    catalog exposes pinned declarations only; it provides no install/readiness
    or configuration-definition authority.
    """
    profiles: ProfileService | None = None
    harnesses: HarnessCatalog | None = None

    def __post_init__(self):
        if (self.profiles is not None and not isinstance(self.profiles, ProfileService)
                or self.harnesses is not None and not isinstance(self.harnesses, HarnessCatalog)):
            raise ContractError('adapter_binding')


class OrdessaReadFacade:
    """Preserve bounded authorised observations over actual current read owners."""
    def __init__(self, services: ReadOwners, *, namespace, read_context, max_items=64):
        if (not isinstance(services, ReadOwners) or not isinstance(read_context, ReadContext)
                or type(max_items) is not int or not 1 <= max_items <= 64):
            raise ContractError('adapter_binding')
        name(namespace)
        self.__services = services
        self.namespace = namespace
        self.__context = read_context
        self.max_items = max_items

    def _authorise(self, context):
        if (not isinstance(context, ReadContext) or context.authority is not self.__context.authority
                or context.scope_ref != self.__context.scope_ref):
            raise ContractError('read_refused')

    def _observation(self, identity, version, data, label):
        ref = ExternalRef(self.namespace, identity)
        return VersionedObservation(digest('descriptor', {'kind': label, 'identity': identity, 'data': data}),
            ref, version, digest('descriptor', data), datetime.now(timezone.utc).isoformat(), data,
            'current' if version is not None else 'unknown',
            evidence_refs=({'source_namespace': self.namespace, 'identity': identity},))

    async def observe(self, query, read_context):
        self._authorise(read_context)
        if not isinstance(query, ObservationQuery):
            raise ContractError('query_unregistered')
        s = self.__services
        p = query.parameters
        values = []
        complete = False
        unknown = []
        if query.kind == 'providers':
            if p:
                raise ContractError('query_parameters')
            if s.harnesses is None:
                raise ContractError('harness_catalog_unbound')
            for descriptor in s.harnesses.descriptors():
                # Use the actual SDK definition identity. Do not fabricate the
                # retired Environment providerRef/admission generation.
                value = descriptor.projection()
                values.append(self._observation(value['definitionRef'], value['definitionRef']['revision'], value, 'provider'))
            unknown = ['installation', 'availability', 'directory_scope', 'provider_admission']
        elif query.kind == 'profiles':
            if p:
                raise ContractError('query_parameters')
            if s.profiles is None:
                raise ContractError('profile_owner_unbound')
            for value in s.profiles.list():
                values.append(self._observation(encode_revision_ref(value.current_revision), str(value.version), encode_profile(value), 'profile'))
            unknown = ['permission_filtered_items']
        elif query.kind == 'profile':
            if set(p) != {'profile_ref'}:
                raise ContractError('query_parameters')
            if s.profiles is None:
                raise ContractError('profile_owner_unbound')
            ref = decode_revision_ref(plain(p['profile_ref']))
            value = s.profiles.get_revision(ref)
            values = [self._observation(encode_revision_ref(ref), str(ref.revision),
                {'profileRef': encode_revision_ref(ref), 'content': encode_content(value.content)}, 'profile')]
            complete = True
        elif query.kind == 'nodes':
            if p:
                raise ContractError('query_parameters')
            # AgentManager.get requires an exact start request and invocation.
            # It is not an authorised inventory list; old Unit nodes are not
            # substituted and absence is never represented by a fabricated [].
            raise ContractError('agent_inventory_owner_unbound')
        elif query.kind == 'configuration':
            if set(p) != {'node_ref'}:
                raise ContractError('query_parameters')
            raise ContractError('instance_configuration_read_owner_unbound')
        else:
            if set(p) != {'definition_ref'}:
                raise ContractError('query_parameters')
            raise ContractError('configuration_definition_owner_unbound')
        truncated = len(values) > self.max_items
        return ObservationBatch(query.kind, tuple(values[:self.max_items]), complete and not truncated,
            'public authorised observation; sources checked independently; no global snapshot',
            pagination={'truncated': truncated, 'count': min(len(values), self.max_items)},
            unobserved_items=tuple(unknown))


class OwnerProposalValidator:
    """Explicitly pins a public owner input mapping; no private provider access."""
    def __init__(self, providers, *, input_builder, read_context, input_verifier=None):
        if not callable(input_builder) or not isinstance(read_context,ReadContext) or (input_verifier is not None and not callable(input_verifier)): raise ContractError('validator_binding')
        self.__providers=providers; self.__builder=input_builder; self.__context=read_context
        self.__verifier=input_verifier
    async def validate(self,draft,basis,read_context):
        if not isinstance(read_context,ReadContext) or read_context.authority is not self.__context.authority or read_context.scope_ref!=self.__context.scope_ref: raise ContractError('read_refused')
        input=self.__builder(draft,basis)
        if not isinstance(input,OwnerProposalInput): raise ContractError('owner_input')
        # Different digest domains cannot prove a semantic field mapping. The
        # host must supply an independently reviewed pure mapping check; absence
        # or ambiguity fails closed before invoking the owner. This is trusted
        # assembly, never a check selected or generated by the decision model.
        if self.__verifier is None: raise ContractError('owner_mapping_unverified')
        if self.__verifier(draft,basis,input) is not True: raise ContractError('owner_mapping_mismatch')
        expected=tuple({'obligationId':o.obligation_id,'requirement':o.requirement,
            'checkerId':o.validator_kind,'checkerVersion':o.version_constraint}
            for o in draft.required_validation_obligations)
        if plain(input.required_obligations)!=plain(expected): raise ContractError('owner_obligation_mapping')
        # Local map freezes the exact two separate digest domains before public call.
        mapping=freeze({'decision_proposal_digest':draft.proposal_digest,'source_input_digest':input.input_digest})
        result=self.__providers.assess_configuration_proposal(input)
        if result.input_digest!=mapping['source_input_digest'] or draft.proposal_digest!=mapping['decision_proposal_digest']: raise ContractError('owner_digest_mismatch')
        rows=tuple(ObligationResult(v['obligationId'],v['status'],v['checkerId'],v['checkerVersion'],v['sourceVersions'],tuple(v['evidenceRefs'])) for v in result.obligation_results)
        receipt=ValidationReceipt('ordessa.owner','1',draft.proposal_digest,result.status,rows,
            datetime.now(timezone.utc).isoformat(),result.validation_scope,result.source_versions,tuple(plain(v) for v in result.issues))
        if receipt.status=='valid': validate_ready(draft,receipt)
        return receipt
