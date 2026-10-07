"""Transport-only projection of the core-owned Agent public contract."""
from __future__ import annotations
import json

from ordessa_environment_api import (
    AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError, ComparisonUnavailableError,
    UnknownResultError, RequestKey,
)
from ordessa_environment_api.domain import DomainRevisionConflict
from ordessa_environment_api.operations import safe_json
from pacthold.agents.public import (
    AGENT_CONTRACT_VERSION, ProfileNotFound, ProfileRef, ProfileRevisionConflict, ProfileValidationError,
    agent_services, wire_contract, wire_schema_digest,
    AGENT_MANAGEMENT_CONTRACT_VERSION, ApplicationPolicy, ConfigurationChangeRequest,
    ConfigurationContractError, ConfigurationUnsupported, decode_node_ref,
    InvocationAuthorityRefused, ConfigurationRevisionConflict,
    ConfigurationOmissionRefused, OperationNotFound,
)
from server_plugin_api import ServerMethodDescriptor, WireError


def agent_core_methods(environment_resolver, *, contract_version=AGENT_CONTRACT_VERSION):
    """Bind to the current host lifecycle, never create an Environment here."""
    schema=wire_contract(contract_version)
    configuration_actions={'describeConfiguration','inspectConfiguration','applyConfiguration','queryChange'}
    profile_application_action='applyProfile'
    provider_actions={'providersList','providersDescribe'}
    node_observation_actions={'nodesList','nodeRead'}
    lifecycle_actions={'stop','release','recover'}
    # Operation metadata reads are a /3 constant: read-only, no capability
    # key; the read ACL is still checked by the core on every call.
    operation_read_actions={'operationRead'}
    profile_actions={item['action'] for item in wire_contract()['methods'].values()}
    def handler(action, definition):
        def invoke(params):
            try:
                if (not isinstance(params, dict)
                        or not set(definition["required"]) <= params.keys()
                        or params.keys() - set(definition["required"] + definition["optional"])):
                    raise ValueError("parameter shape mismatch")
                for name in ("profileId", "displayName", "requestId"):
                    if name in params and (not isinstance(params[name], str) or not params[name]):
                        raise ValueError("nonempty string required")
                if "expectedCatalogRevision" in params and (
                    type(params["expectedCatalogRevision"]) is not int or params["expectedCatalogRevision"] < 1
                ):
                    raise ValueError("positive revision required")
                if type(params.get("includeArchived", False)) is not bool:
                    raise ValueError("boolean required")
                if any(name in params and not isinstance(params[name],dict) for name in ('context','options','preconditions')):
                    raise ValueError('structured preparation parameters required')
                if action in {'prepare', profile_application_action}:
                    has_profile_ref = 'profileRef' in params
                    has_manifest = 'profileManifest' in params
                    if has_profile_ref == has_manifest:
                        raise ValueError('exactly one Profile source required')
                    if has_manifest and not isinstance(params['profileManifest'], dict):
                        raise ValueError('Profile manifest must be an object')
                refs = {name: ProfileRef.from_dict(params[name])
                        for name in ("profileRef", "baseManifestRef", "baseProfileRef") if name in params}
                node_ref=decode_node_ref(params['nodeRef']) if 'nodeRef' in params else None
                change=ConfigurationChangeRequest.from_dict(params['change']) if 'change' in params else None
                application_policy = None
                if action == profile_application_action:
                    policy = params['applicationPolicy']
                    if not isinstance(policy, dict) or set(policy) != {'allowDeferred', 'allowRestart'}:
                        raise ValueError('application policy shape mismatch')
                    application_policy = ApplicationPolicy(policy['allowDeferred'], policy['allowRestart'])
                    if (not isinstance(params['expectedConfigurationRevision'], str)
                            or not params['expectedConfigurationRevision']):
                        raise ValueError('expected configuration revision required')
                if 'definitionRef' in params:
                    ref=params['definitionRef']
                    if (not isinstance(ref,dict)
                            or set(ref)!={'environmentNamespace','definitionId','revision'}
                            or any(not isinstance(value,str) or not value for value in ref.values())):
                        raise ValueError('complete definition reference required')
                if "requestId" in params:
                    RequestKey("parameter-check", "local", params["requestId"])
            except (ValueError, TypeError, KeyError, IdentityMismatchError):
                raise WireError("INVALID_REQUEST", "Agent parameters are invalid", {"retryable": False}) from None
            try:
                services=agent_services(environment_resolver())
                catalog=services.profiles
                if action == "capabilities":
                    result={"contractVersion": contract_version,
                            "schemaDigest": wire_schema_digest(contract_version), "schema": wire_contract(contract_version),
                            "environmentNamespace": catalog.environment_namespace,
                            "supports": dict(catalog.capabilities())}
                    if contract_version==AGENT_MANAGEMENT_CONTRACT_VERSION:
                        result['supports'].update(services.configuration.capabilities())
                        result['supports'].update(services.assembly.capabilities())
                        result['supports'].update(services.lifecycle.capabilities())
                        result['supportedMethods']=[name for name,item in schema['methods'].items()
                            if item['action'] in profile_actions or item['action'] in configuration_actions
                            or item['action'] in provider_actions
                            or item['action'] in node_observation_actions
                            or item['action'] in operation_read_actions
                            or (item['action'] == profile_application_action
                                and result['supports'].get('configurationManagement') is True)
                            or (item['action'] in {'prepare','queryPreparation'} and result['supports']['nodePreparation'])
                            or (item['action'] in {'stop','release','recover'} and result['supports'].get('nodeLifecycle') is True)]
                    return result
                if action=='operationRead':
                    return json.loads(safe_json(services.operations.read(params['operationRef'])))
                if action=='providersList':
                    return {'providers':list(services.providers.list())}
                if action=='providersDescribe':
                    return services.providers.describe(params['definitionRef'])
                if action=='nodesList':
                    return json.loads(safe_json({'nodes': services.nodes.list()}))
                if action=='nodeRead':
                    node = services.nodes.read(node_ref)
                    return {'node': json.loads(safe_json({'node': node}))['node']}
                if action=='queryPreparation':
                    operation=services.assembly.query(catalog.request_key(params['requestId']))
                    return json.loads(safe_json({'operation': None if operation is None else services.assembly.operation_view(operation)}))
                if action=='prepare':
                    operation=services.assembly.prepare(catalog.request_key(params['requestId']),
                        refs.get('profileRef'),params['context'],params['options'],
                        profile_manifest=params.get('profileManifest'))
                    return json.loads(safe_json(services.assembly.operation_view(operation)))
                if action in lifecycle_actions:
                    return json.loads(safe_json(getattr(services.lifecycle, action)(
                        catalog.request_key(params['requestId']), node_ref, params['preconditions'])))
                if action in configuration_actions or action == profile_application_action:
                    manager=services.configuration
                    if action == profile_application_action:
                        if manager.capabilities().get('configurationManagement') is not True:
                            raise ConfigurationUnsupported('Agent configuration management is not composed')
                        operation=manager.apply_profile(
                            catalog.request_key(params['requestId']), node_ref,
                            refs.get('profileRef'), params['expectedConfigurationRevision'],
                            application_policy, base_profile_ref=refs['baseProfileRef'],
                            profile_manifest=params.get('profileManifest'))
                        return manager.operation_view(operation)
                    if action=='describeConfiguration':
                        return {'descriptions':[item.to_dict() for item in manager.describe(node_ref)]}
                    if action=='inspectConfiguration':
                        return manager.inspect(node_ref).to_dict()
                    if action=='applyConfiguration':
                        request=catalog.request_key(change.request_id)
                        operation=manager.apply(request,node_ref,change)
                    else:
                        operation=manager.query(node_ref,params['operationRef'])
                    return manager.operation_view(operation)
                if action not in profile_actions:
                    raise ConfigurationUnsupported('Agent management operation not composed')
                if action == "list":
                    return {"entries": [entry.to_dict() for entry in catalog.list(
                        include_archived=params.get("includeArchived", False))]}
                if action == "readEntry":
                    return catalog.read_entry(params["profileId"]).to_dict()
                if action in {"read", "preview", "clone"}:
                    ref = refs["profileRef"]
                    if action == "read":
                        manifest = catalog.read(ref)
                        return {"ref": manifest.ref.to_dict(), "content": manifest.content}
                    if action == "preview":
                        return dict(catalog.preview(ref))
                request = catalog.request_key(params["requestId"])
                if action == "create":
                    result = catalog.create(profile_id=params["profileId"],
                                            display_name=params["displayName"],
                                            manifest=params["manifest"], request=request)
                elif action == "clone":
                    result = catalog.clone(ref, profile_id=params["profileId"],
                                           display_name=params["displayName"], request=request)
                elif action == "edit":
                    result = catalog.edit(params["profileId"], manifest=params["manifest"],
                        expected_catalog_revision=params["expectedCatalogRevision"],
                        base_manifest_ref=refs["baseManifestRef"], request=request)
                else:
                    kwargs = {"expected_catalog_revision": params["expectedCatalogRevision"], "request": request}
                    if action == "rename":
                        kwargs["display_name"] = params["displayName"]
                    result = getattr(catalog, action)(params["profileId"], **kwargs)
                return result.to_dict()
            except ConfigurationOmissionRefused as exc:
                raise WireError('INVALID_REQUEST',
                    'Profile omits declarations that require explicit reset or disabled actions',
                    {'retryable':False, 'internalCode':exc.code,
                     'omittedDeclarationIds':list(exc.omitted)}) from None
            except ConfigurationUnsupported:
                raise WireError('CAPABILITY_UNSUPPORTED','Required Agent capability unavailable',{'retryable':False}) from None
            except ConfigurationContractError:
                raise WireError('INVALID_REQUEST','Agent configuration parameters are invalid',{'retryable':False}) from None
            except (ProfileRevisionConflict, DomainRevisionConflict, ConfigurationRevisionConflict):
                raise WireError("CONFLICT_VERSION", "Agent revision comparison failed", {"retryable": False}) from None
            except IdentityMismatchError:
                raise WireError("CONFLICT_REQUEST", "Request or reference identity conflict", {"retryable": False}) from None
            except (AdmissionRefusedError,InvocationAuthorityRefused):
                raise WireError("FORBIDDEN", "Profile access refused", {"retryable": False}) from None
            except GuaranteeUnavailableError:
                raise WireError("CAPABILITY_UNSUPPORTED", "Required core guarantee unavailable", {"retryable": False}) from None
            except (UnknownResultError, ComparisonUnavailableError):
                raise WireError("OUTCOME_UNKNOWN", "Request outcome is unknown; do not resend", {"retryable": False}) from None
            except ProfileNotFound:
                raise WireError("NOT_FOUND", "Profile reference not found", {"retryable": False}) from None
            except OperationNotFound:
                # Includes the cross-principal same-shape and dual-ACL hides.
                raise WireError("NOT_FOUND", "Operation reference not found", {"retryable": False}) from None
            except ProfileValidationError:
                raise WireError("INVALID_REQUEST", "Profile parameters are invalid", {"retryable": False}) from None
            except Exception:
                # A failure not proven to precede commit cannot assert that an
                # effect did not occur. It never grants a retry permission.
                if definition['effectful']:
                    raise WireError("OUTCOME_UNKNOWN", "Profile change could not be confirmed; inspect results", {"retryable": False}) from None
                raise WireError("UNAVAILABLE", "Core observation unavailable", {"retryable": False}) from None
        return invoke

    return tuple(ServerMethodDescriptor(method_id=method,
        required_params=frozenset(binding["required"]),
        optional_params=frozenset(binding["optional"]),
        handler=handler(binding["action"], binding), owner="pacthold.agents")
        for method, binding in schema["methods"].items())
