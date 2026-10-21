"""Strict ingress checks for the persisted product-selection document."""
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from ordessa_interfaces.system_access.access_control.authentication import (
    AccessGrant, InstanceAccessAuthority,
)
from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_agents.profiles import ProfileNotFound
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_server.composition.product_user_configuration import (
    ProductUserConfigurationError,
    resolve_product_user_configuration,
)


@contextmanager
def _admitted_context():
    scope = WireScope("realm", "project")
    authority = InstanceAccessAuthority(
        lambda: "controlled-reader-token", principal_id="reader",
        legacy_principal=None,
        grants=(AccessGrant(scope, ("engineering.reviews.query",)),),
    )
    caller = authority.authenticate("Bearer controlled-reader-token")
    access = EngineeringCommandAccess(authority)
    with access.admit(caller, scope, "engineering.reviews.query",
                      request_id="configuration-read", trace_id="configuration-read") as context:
        yield scope, context, access


def _document():
    return {
        "version": 1,
        "piSelection": {
            "agentId": "selected-agent",
            "profileRevision": {
                "environmentNamespace": "realm", "profileId": "selected-profile",
                "manifestRevision": 1, "contentDigest": "sha256:" + "a" * 64,
            },
            "environment": {"id": "environment/existing", "provider": "local",
                            "isolation": "none", "sharing": True},
            "model": {"declarationId": "selected-model", "provider": "opencode",
                      "model": "selected-model-id"},
        },
        "engineering": {"proposalRef": {}, "phases": [], "materialSubmissions": []},
    }


def _trusted_launch():
    return {"bridge_executable": "/trusted/bridge", "bridge_sha256": "a" * 64,
            "pi_executable": "/trusted/pi", "credential_source": "credential-reference"}


def test_user_document_rejects_unknown_callback_or_secret_fields_before_owner_reads():
    with _admitted_context() as (scope, context, access):
        factory = object()
        methods = SimpleNamespace(factory=factory)
        profiles = SimpleNamespace(get_revision=lambda ref: pytest.fail("Profile read before schema validation"))
        environments = SimpleNamespace(get=lambda ref: pytest.fail("Environment read before schema validation"))
        document = _document()
        document["callback"] = "module:function"
        document["apiKey"] = "must-not-be-accepted"
        with pytest.raises(ProductUserConfigurationError, match="invalid configuration fields"):
            resolve_product_user_configuration(
                document, profile_service=profiles, environments=environments,
                context=context, factory=factory, method_control=methods, access=access,
                scope=scope, method_ref=object(), model_catalogue=("selected-model-id",),
                trusted_launch=_trusted_launch(),
            )


def test_trusted_launch_is_not_read_from_user_document():
    with _admitted_context() as (scope, context, access):
        factory = object()
        methods = SimpleNamespace(factory=factory)
        profiles = SimpleNamespace(get_revision=lambda ref: pytest.fail("Profile read before launch validation"))
        environments = SimpleNamespace(get=lambda ref: pytest.fail("Environment read before launch validation"))
        with pytest.raises(ProductUserConfigurationError, match="invalid trusted launch policy"):
            resolve_product_user_configuration(
                _document(), profile_service=profiles, environments=environments,
                context=context, factory=factory, method_control=methods, access=access,
                scope=scope, method_ref=object(), model_catalogue=("selected-model-id",),
                trusted_launch={**_trusted_launch(), "untrusted": "rejected"},
            )


def test_json_reader_reaches_original_profile_lookup_with_actual_context_namespace():
    with _admitted_context() as (scope, context, access):
        factory = object()
        methods = SimpleNamespace(factory=factory)
        received = []

        class ProfileLookup:
            def get_revision(self, ref):
                received.append(ref)
                raise ProfileNotFound("the selected revision is not persisted")

        with pytest.raises(ProfileNotFound):
            resolve_product_user_configuration(
                json.dumps(_document()), profile_service=ProfileLookup(),
                environments=SimpleNamespace(get=lambda ref: pytest.fail("Environment read after missing Profile")),
                context=context, factory=factory, method_control=methods, access=access,
                scope=scope, method_ref=object(), model_catalogue=("selected-model-id",),
                trusted_launch=_trusted_launch(),
            )
        assert len(received) == 1
        assert received[0].environment_namespace == scope.realm_id


def test_json_reader_rejects_duplicate_keys_and_oversized_input():
    with _admitted_context() as (scope, context, access):
        factory = object()
        methods = SimpleNamespace(factory=factory)
        inert = SimpleNamespace(get_revision=lambda ref: pytest.fail("Profile read before JSON decode"))
        common = dict(profile_service=inert,
                      environments=SimpleNamespace(get=lambda ref: pytest.fail("Environment read")),
                      context=context, factory=factory, method_control=methods, access=access,
                      scope=scope, method_ref=object(), model_catalogue=("selected-model-id",),
                      trusted_launch=_trusted_launch())
        with pytest.raises(ProductUserConfigurationError, match="invalid configuration JSON"):
            resolve_product_user_configuration('{"version":1,"version":1}', **common)
        with pytest.raises(ProductUserConfigurationError, match="1 MiB"):
            resolve_product_user_configuration(" " * (1_048_577), **common)
