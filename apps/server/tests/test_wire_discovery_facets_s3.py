"""T014-S3: `server.hello`'s discovery facets arrive as contributions.

Before this slice the host transport *built* the domain half of the discovery
answer: it walked the harness directory it was handed and it validated the
native identity of the deployment it serves. Both are business facts, and
FR-006 says the host may carry them, not read them. Now the ACP harness plugin
publishes `facet name -> projector` through the open `wire.discovery-facets`
point and the host keeps only the envelope, the aggregation and the order.

The acceptance questions this file answers, each with the counter-example that
makes the answer mean something:

1. with the harness plugin composed, the facet's answer is *byte-identical* to
   what the host used to build — checked against a verbatim transcription of
   the deleted block, not against a re-derivation of it;
2. without it, hello answers `harnesses: []` and no `nativeExecution` key at
   all — typed absence, proved on a composition where the directory **is**
   present, so an empty list cannot be an empty directory wearing a costume;
3. the native-identity refusal keeps its family, its message and its internal
   code after moving into a plugin, and the family is now *named* rather than
   fallen through (the retired order-101 red, re-pinned at its new home);
4. the aggregate is per composition, never module state: two live hosts in one
   process publish nothing into each other's hello, probed in both orders;
5. the host still owns the aggregation rules it is allowed to own: the envelope
   is not a facet, one facet has one owner, a projector is a callable, and
   retiring the owner takes the facet away with it.
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

from fastapi.testclient import TestClient
import pytest

from ordessa_harness.server_acp.plugin import PLUGIN_ID as ACP_PLUGIN_ID
from ordessa_server.bootstrap import build_runtime
from ordessa_server.transport.http import create_app
from ordessa_server.wire import discovery as discovery_module
from ordessa_server.wire.discovery import (
    DiscoveryFacetAggregate,
    DiscoveryFacetContributionRefused,
)
from ordessa_server.wire.errors import FAMILIES, WireError
from ordessa_server_compat.composition import build_runtime_from_native_adapter
from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry
from ordessa_server_compat.plugin import ServerCompatPlugin
from ordessa_server_product.composition import create_composition
from ordessa_workspace.plugin import WorkspaceServerPlugin
from server_plugin_api import (
    WIRE_DISCOVERY_FACETS_API_VERSION,
    WIRE_DISCOVERY_FACETS_POINT_ID,
    Contribution,
    ContributionBatch,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

HELLO = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}
HARNESS_ROOT = Path(__file__).resolve().parents[3] / "plugins" / "harness"
ACP_PLUGIN_SOURCE = HARNESS_ROOT / "src" / "ordessa_harness" / "server_acp" / "plugin.py"

#: wire/1's frozen member order for the default product's hello answer. A facet
#: may add members; it may not reorder the ones the contract already has.
FROZEN_MEMBER_ORDER = (
    "serverId", "protocolVersion", "capabilities", "auth", "harnesses",
)

#: The three seats below, in the directory's own (sorted) order.
SEAT_IDS = ["alpha", "beta", "gamma"]


def _registry() -> HarnessRegistry:
    """Three seats covering each publishing branch the old block had.

    One with a credential kind, one with a model control, one with neither:
    the deleted code published those two keys conditionally, and a reference
    comparison over a directory that exercised only one branch would pass for
    a projector that dropped the other.
    """
    reg = HarnessRegistry()
    reg.register(HarnessDescriptor(
        "alpha", credential_kind="alpha-key", capability_claims={"stream": True},
        configuration_validator=lambda value: None if isinstance(value, dict) else ValueError(),
    ))
    reg.register(HarnessDescriptor(
        "beta", model_control_id="model", control_options={"model": ()},
        configuration_validator=lambda value: None if isinstance(value, dict) else ValueError(),
    ))
    reg.register(HarnessDescriptor(
        "gamma", configuration_validator=lambda value: None if isinstance(value, dict) else ValueError(),
    ))
    return reg


def _reference_harnesses(directory) -> "list[dict[str, Any]]":
    """The deleted host block, transcribed verbatim from pre-S3
    `ordessa_server/wire/handlers.py` (only the loop variables kept).

    This is deliberately a copy of the OLD code and not a restatement of the
    new: if the projector drifts from what the host used to answer, the
    comparison against it goes red.
    """
    harnesses = []
    for harness_id in (directory.registered() if directory is not None else ()):
        descriptor = directory.get(harness_id)
        entry: dict[str, Any] = {"id": harness_id}
        if descriptor.credential_kind is not None:
            entry["credentialKind"] = descriptor.credential_kind
        if descriptor.model_control_id is not None:
            entry["modelControlId"] = descriptor.model_control_id
        harnesses.append(entry)
    return harnesses


@contextlib.contextmanager
def _serving(runtime):
    """One started Server, several requests, exactly one teardown."""
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        assert client.get("/live").status_code == 200
        yield client


def _hello(client, runtime) -> dict[str, Any]:
    """One real `server.hello` through the transport (never a hand-built dict)."""
    body = client.post("/wire/v1/server.hello", headers={
        "Authorization": f"Bearer {runtime.token}",
    }, json={"jsonrpc": "2.0", "id": "1", "method": "server.hello",
             "params": HELLO}).json()
    assert "result" in body, body
    return body["result"]


class _FacetPlugin:
    """A stand-in domain that publishes whatever facet payload it is handed."""

    def __init__(self, plugin_id: str, payload: Any) -> None:
        self._id = plugin_id
        self._payload = payload

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(id=self._id, display_name="facet", version="1")

    def build(self, context) -> ServerPluginRegistration:
        return ServerPluginRegistration(contributions=ContributionBatch((
            Contribution(
                point_id=WIRE_DISCOVERY_FACETS_POINT_ID,
                api_version=WIRE_DISCOVERY_FACETS_API_VERSION,
                payload=self._payload,
            ),
        )))


# -- 1: the composed facet answers exactly what the host used to build -------


def test_the_harness_facet_answers_byte_identically_to_the_deleted_host_block(tmp_path):
    directory = _registry()
    runtime = build_runtime(
        tmp_path / "full",
        server_plugins=create_composition().compatibility_plugins(harnesses=directory))
    try:
        with _serving(runtime) as client:
            result = _hello(client, runtime)
            assert json.dumps(result["harnesses"]) == json.dumps(
                _reference_harnesses(directory)), (
                "the facet's answer drifted from what the host built before S3")
            # The reference itself has to be non-trivial or the comparison
            # above proves nothing: both conditional keys and the bare case
            # are published here.
            assert [entry["id"] for entry in result["harnesses"]] == SEAT_IDS
            assert result["harnesses"][0]["credentialKind"] == "alpha-key"
            assert result["harnesses"][1]["modelControlId"] == "model"
            assert set(result["harnesses"][2]) == {"id"}
            # The envelope and the order are still the host's.
            assert list(result) == list(FROZEN_MEMBER_ORDER), list(result)
            assert result["protocolVersion"] == "wire/1"
            assert result["auth"] == {"required": True, "schemes": ["session_token"]}
            assert "nativeExecution" not in result
            # And the answer belongs to the domain that projected it.
            assert runtime.plugin_host.wire_discovery_facets.contributed_facets() == {
                "harnesses": ACP_PLUGIN_ID, "nativeExecution": ACP_PLUGIN_ID,
            }
    finally:
        runtime.stop()


def test_a_seat_registered_after_activation_is_advertised_by_the_next_hello(tmp_path):
    """Projectors, not values: the directory is a live fact.

    An activation-time snapshot would answer a stale list here, and a client
    that chose nothing from it would never learn the seat exists.
    """
    directory = _registry()
    runtime = build_runtime(
        tmp_path / "live",
        server_plugins=create_composition().compatibility_plugins(harnesses=directory))
    try:
        with _serving(runtime) as client:
            assert "delta" not in [
                entry["id"] for entry in _hello(client, runtime)["harnesses"]]
            directory.register(HarnessDescriptor(
                "delta", credential_kind="delta-key",
                configuration_validator=lambda value: None if isinstance(value, dict) else ValueError(),
            ))
            result = _hello(client, runtime)
            assert [entry["id"] for entry in result["harnesses"]] == [
                "alpha", "beta", "delta", "gamma"]
            assert json.dumps(result["harnesses"]) == json.dumps(
                _reference_harnesses(directory))
    finally:
        runtime.stop()


# -- 2: absence is typed, not a refusal and not an empty costume -------------


def test_a_composition_without_the_harness_plugin_answers_an_absent_facet(tmp_path):
    """The directory IS composed here; only its projector is gone.

    This is the decisive shape of the absence check: a composition holding a
    populated harness directory but composing no harness plugin must answer
    `harnesses: []` — so the empty list is the contract's member with nothing
    in it, and cannot be mistaken for a host that still read the port itself.
    """
    directory = _registry()
    runtime = build_runtime(
        tmp_path / "no-acp",
        server_plugins=(WorkspaceServerPlugin(), ServerCompatPlugin(harnesses=directory)))
    try:
        assert runtime.plugin_host.provided_port("harness.directory") is directory
        assert list(directory.registered()) == SEAT_IDS
        with _serving(runtime) as client:
            result = _hello(client, runtime)
            assert result["harnesses"] == []
            assert "nativeExecution" not in result, "typed absence, not a null member"
            assert list(result) == list(FROZEN_MEMBER_ORDER)
            assert runtime.plugin_host.wire_discovery_facets.facets() == {}
    finally:
        runtime.stop()


def test_a_bare_host_still_answers_the_contract_members(tmp_path):
    runtime = build_runtime(tmp_path / "bare", server_plugins=[])
    try:
        with _serving(runtime) as client:
            result = _hello(client, runtime)
            assert result["harnesses"] == []
            assert "nativeExecution" not in result
            assert [item["id"] for item in result["capabilities"]] == ["server.hello"]
    finally:
        runtime.stop()


def test_unloading_the_harness_plugin_takes_its_facet_with_it(tmp_path):
    directory = _registry()
    runtime = build_runtime(
        tmp_path / "retire",
        server_plugins=create_composition().compatibility_plugins(harnesses=directory))
    try:
        with _serving(runtime) as client:
            assert _hello(client, runtime)["harnesses"]
            runtime.plugin_host.deactivate(ACP_PLUGIN_ID)
            result = _hello(client, runtime)
            assert result["harnesses"] == [], "a retired owner's facet is not a value"
            assert "nativeExecution" not in result
            assert runtime.plugin_host.wire_discovery_facets.facets() == {}
            # and the directory it read from is untouched — the facet left,
            # not the deployment fact it was projected from.
            assert list(directory.registered()) == SEAT_IDS
    finally:
        runtime.stop()


# -- 3: the moved native-identity rule keeps wire/1's bytes ------------------


def _native(root: Path):
    return build_runtime_from_native_adapter(
        root, plugin_root=HARNESS_ROOT, harness_id="pi",
        adapter_command=shutil.which("node"), adapter_args=("/not-launched.mjs",),
    )


def _archive_native_profile(runtime) -> None:
    """Make the declared identity unusable the way a deployment does it."""
    with runtime.database.transaction() as conn:
        conn.execute("UPDATE server_profiles SET archived_at='2026-01-01' WHERE id=?",
                     (runtime.native_profile_id,))


def test_an_invalid_native_identity_still_refuses_with_the_same_family_and_code(tmp_path):
    runtime = _native(tmp_path / "native")
    try:
        runtime.start()
        assert runtime.wire.hello(HELLO)["nativeExecution"] == {
            "mode": "native", "harness": "pi", "profileId": runtime.native_profile_id,
        }
        _archive_native_profile(runtime)
        with pytest.raises(WireError) as refused:
            runtime.wire.hello(HELLO)
        error = refused.value
        assert error.family == "UNAVAILABLE"
        assert error.message == "native execution identity is unavailable"
        assert error.details == {"internalCode": "SERVER_NATIVE_IDENTITY_INVALID"}
    finally:
        runtime.stop()


def test_the_native_refusal_reaches_the_client_as_the_same_body(tmp_path):
    runtime = _native(tmp_path / "native-transport")
    try:
        runtime.start()
        _archive_native_profile(runtime)
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            body = client.post("/wire/v1/server.hello", headers={
                "Authorization": f"Bearer {runtime.token}",
            }, json={"jsonrpc": "2.0", "id": "1", "method": "server.hello",
                     "params": HELLO}).json()
        assert body["error"]["code"] == "UNAVAILABLE", body
        assert body["error"]["message"] == "native execution identity is unavailable"
        assert body["error"]["details"]["internalCode"] == "SERVER_NATIVE_IDENTITY_INVALID"
    finally:
        runtime.stop()


def test_the_moved_construction_names_the_family_explicitly():
    """The order-101 discipline, pinned at the code's new home.

    The retired red was
    `test_wire_error_family_101.py::test_no_wire_error_is_constructed_with_a_non_family_first_argument`,
    whose scan covered only the host transport and the compatibility core's
    wire module. The construction moved out of both, so the same scan runs
    here over the plugin that now raises it: an internal code sitting in the
    family slot would go back to converging by accident instead of being a
    chosen family, and the code that says WHICH error it was belongs in
    `details` only.
    """
    source = ACP_PLUGIN_SOURCE.read_text(encoding="utf-8")
    found = re.findall(r'WireError\(\s*"([A-Z_]+)"', source)
    found += re.findall(r'WireError\(\s*\n\s*"([A-Z_]+)"', source)
    assert "UNAVAILABLE" in found, "the native-identity refusal no longer names its family"
    illegal = sorted({name for name in found if name not in FAMILIES})
    assert illegal == [], illegal
    internal = re.findall(r'"internalCode":\s*"([A-Z_]+)"', source)
    assert "SERVER_NATIVE_IDENTITY_INVALID" in internal, internal
    assert "SERVER_NATIVE_IDENTITY_INVALID" not in found, (
        f"the internal code is back in a family slot: {found}")
    for name in sorted(set(found)):
        WireError(name, "constructed for real")


# -- 4: per composition, never module state ---------------------------------


def test_two_live_compositions_in_one_process_do_not_see_each_others_facet(tmp_path):
    """A bare host composed first, a harnessed one while it stays live.

    Module-level state — the shape this slice must never regress to — publishes
    the second host's facet into the first host's hello, and both hosts are
    live at the same moment here, so no teardown hides it. A third bare host
    composed LAST covers the other direction: a facet published by a host that
    is already live must not reach a host that composes no producer.
    """
    bare_first = build_runtime(tmp_path / "bare-first", server_plugins=[])
    directory = _registry()
    harnessed = build_runtime(
        tmp_path / "harnessed",
        server_plugins=create_composition().compatibility_plugins(harnesses=directory))
    bare_second = build_runtime(tmp_path / "bare-second", server_plugins=[])
    try:
        with _serving(bare_first) as first_client:
            with _serving(harnessed) as harnessed_client:
                with _serving(bare_second) as second_client:
                    assert _hello(first_client, bare_first)["harnesses"] == []
                    assert json.dumps(_hello(harnessed_client, harnessed)["harnesses"]) \
                        == json.dumps(_reference_harnesses(directory))
                    assert _hello(first_client, bare_first)["harnesses"] == []
                    assert _hello(second_client, bare_second)["harnesses"] == []
                    assert "nativeExecution" not in _hello(first_client, bare_first)
                    assert "nativeExecution" not in _hello(second_client, bare_second)
                    # The aggregates themselves, read while all three hosts are
                    # alive: a stop() retires a round's contributions, so this
                    # is the only moment the publishing state is observable.
                    assert (bare_first.plugin_host.wire_discovery_facets
                            is not harnessed.plugin_host.wire_discovery_facets)
                    assert (bare_second.plugin_host.wire_discovery_facets
                            is not harnessed.plugin_host.wire_discovery_facets)
                    assert bare_first.plugin_host.wire_discovery_facets.facets() == {}
                    assert bare_second.plugin_host.wire_discovery_facets.facets() == {}
                    assert set(harnessed.plugin_host.wire_discovery_facets.facets()) == {
                        "harnesses", "nativeExecution"}
                    assert harnessed.plugin_host.wire_discovery_facets.contributed_facets() == {
                        "harnesses": ACP_PLUGIN_ID, "nativeExecution": ACP_PLUGIN_ID}
    finally:
        for runtime in (bare_second, harnessed, bare_first):
            runtime.stop()


def test_the_facet_aggregate_is_not_reachable_as_module_state():
    """The per-composition rule, structurally: no host-wide aggregate exists.

    `wire.discovery` may define classes and the contract's constant members;
    an `DiscoveryFacetAggregate` living in its module namespace is exactly the
    shape that let one composition answer another's hello (the S2a-R finding
    this slice must not repeat), and the behavioural test above would only
    catch it for the paths it happens to exercise.
    """
    published = sorted(
        name for name, value in vars(discovery_module).items()
        if isinstance(value, DiscoveryFacetAggregate))
    assert published == [], f"module-level facet state: {published}"
    assert not hasattr(discovery_module, "facets")


# -- 5: the host still owns the aggregation rules ---------------------------


def test_a_facet_may_not_claim_an_envelope_member(tmp_path):
    """`serverId`/`protocolVersion`/`capabilities`/`auth` are the host's."""
    for member in ("serverId", "protocolVersion", "capabilities", "auth"):
        with pytest.raises(DiscoveryFacetContributionRefused) as refused:
            build_runtime(tmp_path / f"reserved-{member}", server_plugins=[
                _FacetPlugin("fake.reserved", {member: lambda: []}),
            ])
        assert member in str(refused.value)
        assert "never overridable" in str(refused.value)


def test_two_owners_for_one_facet_refuse_the_round(tmp_path):
    """One facet, one owner: activation order is not a selection rule."""
    root = tmp_path / "two-owners"
    with pytest.raises(DiscoveryFacetContributionRefused) as refused:
        build_runtime(root, server_plugins=[
            _FacetPlugin("fake.first", {"harnesses": lambda: [{"id": "first"}]}),
            _FacetPlugin("fake.second", {"harnesses": lambda: [{"id": "second"}]}),
        ])
    message = str(refused.value)
    assert "harnesses" in message
    assert "fake.first" in message and "fake.second" in message
    # The refused round left nothing behind, including the data-root lock:
    # composing the same root again is the retry path, not a dead root.
    retry = build_runtime(root, server_plugins=[
        _FacetPlugin("fake.first", {"harnesses": lambda: [{"id": "first"}]}),
    ])
    try:
        with _serving(retry) as client:
            assert _hello(client, retry)["harnesses"] == [{"id": "first"}]
    finally:
        retry.stop()


def test_a_facet_must_carry_a_projector(tmp_path):
    with pytest.raises(DiscoveryFacetContributionRefused) as refused:
        build_runtime(tmp_path / "not-callable", server_plugins=[
            _FacetPlugin("fake.value", {"extra": [{"id": "snapshot"}]}),
        ])
    assert "zero-argument projector" in str(refused.value)


def test_one_owner_may_contribute_several_facets_in_one_batch(tmp_path):
    """The payload is a mapping, and one owner may fill more than one member.

    The order the mapping names them in is the order hello publishes them —
    which is why the harness plugin contributes `harnesses` before
    `nativeExecution` rather than as two batches.
    """
    runtime = build_runtime(tmp_path / "two-facets", server_plugins=[
        _FacetPlugin("fake.two", {
            "harnesses": lambda: [{"id": "own"}],
            "deploymentTag": lambda: {"channel": "canary"},
            "declined": lambda: None,
        }),
    ])
    try:
        with _serving(runtime) as client:
            result = _hello(client, runtime)
            assert result["harnesses"] == [{"id": "own"}]
            assert result["deploymentTag"] == {"channel": "canary"}
            assert "declined" not in result, "None is a declined fact, not a null member"
            assert list(result) == [
                "serverId", "protocolVersion", "capabilities", "auth",
                "harnesses", "deploymentTag"]
    finally:
        runtime.stop()
