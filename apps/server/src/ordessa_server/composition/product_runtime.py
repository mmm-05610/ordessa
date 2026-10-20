"""The same final product composition used by the formal Server entry.

Trusted callers can select Engineering in this runtime. This function creates
no alternate host, manager, authority or database, and selects no model policy.
"""
from collections.abc import Mapping

from ordessa_engineering.application.api import ApplicationError

from .configuration.product_selection import create_host_product_composition
from .engineering_method_unit_assembly import method_unit_application_ports_factory
from .product_user_configuration import resolve_unbound_product_user_configuration
from ordessa_units.public import composed_profile_service


_METHOD_UNIT_REQUIRED = frozenset({
    "proposal_ref", "phases", "author_unit_resolver", "invocation_resolver",
    "unit_query_factory",
})
_METHOD_UNIT_OPTIONAL = frozenset({
    "phase_bindings", "execution_query_factory", "base_ports_factory",
    "confirmation_options",
    "execution_request_factory",
    "material_submissions", "report_phase_key", "dispatch_prompt_parameters",
    "workspace_scope_guard",
})


def _method_unit_configuration(value, *, pi_selection, pi_ports, engineering_options):
    if not isinstance(value, Mapping):
        raise ApplicationError("UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")
    unknown = set(value) - (_METHOD_UNIT_REQUIRED | _METHOD_UNIT_OPTIONAL)
    if unknown or not _METHOD_UNIT_REQUIRED.issubset(value):
        raise ApplicationError("UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")
    if any(not callable(value[name]) for name in (
            "author_unit_resolver", "invocation_resolver", "unit_query_factory")):
        raise ApplicationError("UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")
    if value.get("base_ports_factory") is not None and not callable(value["base_ports_factory"]):
        raise ApplicationError("REVIEW_SOURCE_AUTHORITY_MISMATCH")
    if "phase_bindings" in value and type(value["phase_bindings"]) is not tuple:
        raise ApplicationError("WORK_SOURCE_BINDING_INVALID")
    if "material_submissions" in value and type(value["material_submissions"]) is not tuple:
        raise ApplicationError("REVIEW_AUTHOR_SOURCE_UNAVAILABLE")
    if value.get("report_phase_key") is not None and (
            type(value["report_phase_key"]) is not str or not value["report_phase_key"]):
        raise ApplicationError("SUBMISSION_REPORT_AUTHORITY_MISMATCH")
    if (value.get("execution_query_factory") is not None
            and not callable(value["execution_query_factory"])):
        raise ApplicationError("WORK_NATIVE_SOURCE_UNAVAILABLE")
    if value.get('execution_request_factory') is not None:
        if (not callable(value['execution_request_factory'])
                or value.get('execution_query_factory') is not None):
            raise ApplicationError('WORK_NATIVE_SOURCE_UNAVAILABLE')
    if (value.get('dispatch_prompt_parameters') is not None
            and (not callable(value['dispatch_prompt_parameters'])
                 or value.get('execution_request_factory') is not None
                 or value.get('execution_query_factory') is not None
                 or value.get('report_phase_key') is None)):
        raise ApplicationError('WORK_NATIVE_SOURCE_UNAVAILABLE')
    if (value.get('workspace_scope_guard') is not None
            and (not callable(value['workspace_scope_guard'])
                 or value.get('dispatch_prompt_parameters') is None)):
        raise ApplicationError('DISPATCH_WORK_SCOPE_AUTHORITY_UNAVAILABLE')
    unbound = value["proposal_ref"] is None and value["phases"] is None
    if not unbound and (value["proposal_ref"] is None
            or type(value["phases"]) is not tuple or not value["phases"]):
        raise ApplicationError("METHOD_SUBJECT_BINDING_MISMATCH")
    if pi_selection is None or pi_ports is None:
        raise ApplicationError("UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")
    if "application_ports_factory" in engineering_options:
        raise ApplicationError("REVIEW_SOURCE_AUTHORITY_MISMATCH")
    if not {"library_path", "library_id"}.issubset(engineering_options):
        raise ApplicationError("CAPABILITY_AUTHORITY_UNAVAILABLE")
    if not ("scope" in engineering_options or
            {"realm", "project"}.issubset(engineering_options)):
        raise ApplicationError("CAPABILITY_AUTHORITY_UNAVAILABLE")
    return dict(value)


def build_product_runtime(data_root, *, pi_selection=None, pi_ports=None,
                          method_unit_options=None, native_user_configuration=None,
                          **engineering_options):
    options = None
    if method_unit_options is not None:
        options = _method_unit_configuration(
            method_unit_options, pi_selection=pi_selection, pi_ports=pi_ports,
            engineering_options=engineering_options)
    if native_user_configuration is not None:
        if (type(native_user_configuration) not in (str, bytes)
                or options is None or options["proposal_ref"] is not None
                or options["phases"] is not None):
            raise ApplicationError("METHOD_SUBJECT_BINDING_MISMATCH")
    composition = create_host_product_composition(pi_selection=pi_selection, pi_ports=pi_ports)
    if options is not None:
        selected_pi = composition.selected_pi_execution
        if selected_pi is None:
            raise ApplicationError("UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")
        def application_ports_factory(factory, access, scope):
            runtime = getattr(selected_pi, "_runtime", None)
            unit_owner = getattr(runtime, "unit_execution_owner", None)
            if (runtime is None or getattr(runtime, "started", False)
                    or getattr(getattr(runtime, "wire", None), "identity_authority", None)
                        is not getattr(access, "authority", None)
                    or unit_owner is None):
                raise ApplicationError("UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")
            selected_options = options
            if native_user_configuration is not None:
                selection = selected_pi.selection
                launch = {name: getattr(selection, name) for name in (
                    "bridge_executable", "bridge_sha256", "pi_executable", "credential_source")}
                resolved = resolve_unbound_product_user_configuration(
                    native_user_configuration,
                    profile_service=composed_profile_service(runtime.unit_runtime.context),
                    environments=selected_pi.ports.environments, runtime=runtime,
                    project_id=scope.project_id,
                    model_catalogue=selected_pi.ports.model_catalogue,
                    trusted_launch=launch)
                if (resolved.pi_selection != selection
                        or options.get("material_submissions", ())
                            not in ((), resolved.material_submissions)):
                    raise ApplicationError("REVIEW_SOURCE_AUTHORITY_MISMATCH")
                selected_options = dict(options, material_submissions=resolved.material_submissions)
            constructor = method_unit_application_ports_factory(
                unit_owner=unit_owner, runtime=runtime, **selected_options)
            ports = constructor(factory, access, scope)
            if options["proposal_ref"] is None:
                # Keep the owner instance that the actual review admission and
                # Work source use. Later subject selection calls its original
                # one-shot bind_selection; this is no second subject store.
                bindings = getattr(getattr(ports, "review_admission", None),
                                   "bindings", None)
                if (getattr(bindings, "factory", None) is not factory
                        or not callable(getattr(bindings, "bind_selection", None))
                        or getattr(runtime, "engineering_review_bindings", None) is not None):
                    raise ApplicationError("REVIEW_SOURCE_AUTHORITY_MISMATCH")
                runtime.engineering_review_bindings = bindings
            return ports

        engineering_options = dict(engineering_options)
        engineering_options["application_ports_factory"] = application_ports_factory
    return composition.default_runtime(data_root,
        engineering_options=engineering_options or None)
