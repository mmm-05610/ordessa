"""T05b — what remains in ``registry`` after the admission demotion.

Composition-time refusal (duplicate ids, overlap, claim collisions) is the
platform's job now — see ``test_platform_admission.py`` for the migration of
the old semantics onto ``HarnessContributionRegistry`` + ``stage_contributions``.
This file pins what the package legitimately still owns: the brand adapter
roster, the plugin identity, and the facet naming the domain dialect uses.
"""
from __future__ import annotations

from ordessa_sandbox_adapters import (
    ADAPTER_PLUGIN_ID,
    SANDBOX_NATIVE_CONFIGURATION_CONTRACT_ID,
    ClaudeSandboxAdapter,
    CodexSandboxAdapter,
    PiSandboxAdapter,
    default_sandbox_adapters,
)


def test_default_roster_is_the_three_brands_with_unique_ids():
    adapters = default_sandbox_adapters()
    assert [type(a) for a in adapters] == [CodexSandboxAdapter,
                                           ClaudeSandboxAdapter, PiSandboxAdapter]
    ids = [a.adapter_id for a in adapters]
    assert len(ids) == len(set(ids)) == 3
    assert {a.harness_id for a in adapters} == {"codex", "claude-code", "pi"}


def test_facet_and_plugin_id_keep_their_documented_names():
    # data compatibility (AGENTS rule 5): the contract id and plugin id are
    # the same strings the pre-foundation T05 contribution used.
    assert SANDBOX_NATIVE_CONFIGURATION_CONTRACT_ID == "sandbox.native-configuration@1"
    assert ADAPTER_PLUGIN_ID == "ordessa.sandbox-adapters"


def test_adapters_are_constructible_without_permissions_installed():
    # the roster itself is pure contracts; the Permissions id only ever
    # appeared as a NAME in claim-staging docs and is not imported anywhere.
    for adapter in default_sandbox_adapters():
        assert callable(adapter.compile)
