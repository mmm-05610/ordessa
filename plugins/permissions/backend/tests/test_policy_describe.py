"""T014-Q5: the read-only policy summary `permissions.policy.describe`.

The Permissions Settings region (ux.md §Settings: 规则来源 / 组织上限只读摘要 /
用户默认意图 / 审批历史) had no real read surface: the PolicyRepository was
only readable in-process. This method closes that gap and nothing else: it is
read-only (a byte-for-byte unchanged database proves it), it grants no
authority (there is no ruling in any of its fields), and every entry it
reports comes from stored records — an unwired repository answers empty lists
and `ready: false`, never fabricated defaults.

The shape is closed: the exact response keys, exact per-entry keys; a stored
record carrying a secret-named or oversized extra field is refused outright
(the API's own "unknown fields make the record unverifiable" discipline), so
nothing smuggles a key through this method. `ready` is derived exactly like
the admission port's readiness, and the availability predicate only answers
the hello question — dispatch is never gated by it.
"""
from __future__ import annotations

import json

import pytest
from server_plugin_api import (ACP_ADMISSION_PORT, ServerPluginContext,
                               ServerMethodDescriptor)
from support import admin_ceiling, seeded_database, seed_session

from ordessa_permissions_api import (BrandMode, PermissionIntent, PolicyCeiling,
                                     PolicyRefusal)
from ordessa_permissions_backend import PolicyRepository, PermissionsBackendPlugin
from ordessa_permissions_backend.describe import (
    DESCRIBE_OPTIONAL_PARAMS, DESCRIBE_REQUIRED_PARAMS, POLICY_DESCRIBE_METHOD,
    PolicyDescribe)
from ordessa_permissions_backend.migration import LegacyProfileRulesMigration

CEILING_KEYS = {"policyId", "scope", "revision", "source", "signed",
                "maximumExposure", "effectiveFrom", "hardDenies", "requireApproval"}
ENTRY_KEYS = {"key", "pattern", "action"}
INTENT_KEYS = {"intentId", "revision", "harnessId", "scope", "rules", "desiredMode"}
RULE_KEYS = {"key", "pattern", "action", "priority", "scope"}
REVIEW_KEYS = {"source", "index", "reason"}
NATIVE_EVIDENCE_PORT = "acp.admission.native_evidence"


def build(ports=None, tmp_path=None):
    database = seeded_database(tmp_path)
    seed_session(database)
    extra = dict(ports or {})
    plugin = PermissionsBackendPlugin()
    registration = plugin.build(ServerPluginContext(
        plugin_id="permissions-backend", data_root=tmp_path,
        ports={"database": database, **extra}))
    return database, registration


def descriptor(registration) -> ServerMethodDescriptor:
    hits = [m for m in registration.methods if m.method_id == POLICY_DESCRIBE_METHOD]
    assert len(hits) == 1, f"the method must be declared exactly once: {hits}"
    return hits[0]


def call(registration, params=None) -> dict:
    return descriptor(registration).handler(dict(params or {}))


def seed_policy_data(policies: PolicyRepository) -> None:
    """A signed admin ceiling with entries, and a user intent with a rule."""
    policies.store_ceiling(admin_ceiling(
        deny=[{"key": "edit", "pattern": "/etc/*", "action": "deny"}],
        requireApproval=[{"key": "bash", "action": "ask"}]))
    policies.store_intent(PermissionIntent.of(
        intent_id="intent-user-1", revision=1, harness_id="pi", scope="user",
        rules=[{"key": "read", "action": "allow"},
               {"key": "bash", "pattern": "rm *", "action": "deny"}]))


def run_legacy_migration(policies: PolicyRepository) -> None:
    """A full-access preset is not provably equivalent: needsReview entries."""
    migration = LegacyProfileRulesMigration(policies)
    migration.import_profile({"id": "profile-1", "harness_type": "pi",
                              "permission_preset": "full-access",
                              "permission_rules_json": json.dumps(
                                  [{"key": "read", "action": "allow"}])})


def crafted_ceiling(policies: PolicyRepository, record: dict) -> None:
    """Insert a ceiling row behind the store's back (raw table write).

    The store path refuses an untrusted provenance and any extra field; only a
    raw insert can simulate a stored record this method must then face.
    """
    with policies.database.transaction() as conn:
        conn.execute(
            "INSERT INTO permissions_policy_ceilings"
            "(policy_id,revision,record_json,stored_at) VALUES (?,?,?,?)",
            (str(record["policyId"]), int(record["revision"] or 1),
             json.dumps(record, sort_keys=True), "2026-01-01T00:00:00+00:00"))


def all_rows(database) -> dict:
    with database.read() as conn:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {table: sorted(tuple(r) for r in conn.execute(f"SELECT * FROM {table}"))
                for table in tables}


# -- the declaration ------------------------------------------------------------------

def test_policy_describe_record_vocabulary_matches_the_api():
    """describe.py's closed projection vocabularies must equal the API's own
    record fields, or the summary drifts from what is actually stored."""
    from ordessa_permissions_api import ceilings as ceilings_module
    from ordessa_permissions_api import intents as intents_module
    from ordessa_permissions_api import rules as rules_module
    from ordessa_permissions_backend import describe as describe_module

    assert describe_module._CEILING_FIELDS == ceilings_module._RECORD_FIELDS
    assert (describe_module._INTENT_ALLOWED_FIELDS ==
            intents_module._RECORD_FIELDS)
    assert (describe_module._INTENT_RULE_ALLOWED_FIELDS ==
            rules_module._RULE_FIELDS)


def test_describe_method_descriptor_exact_shape_and_owner(tmp_path):
    _, registration = build(tmp_path=tmp_path)
    method = descriptor(registration)
    assert method.required_params == DESCRIBE_REQUIRED_PARAMS == frozenset()
    assert method.optional_params == DESCRIBE_OPTIONAL_PARAMS == frozenset(
        {"principal", "scope"})
    assert method.owner == "permissions-backend"
    assert callable(method.availability)
    assert all(m.owner == "permissions-backend" for m in registration.methods)


# -- headless proof the data is REAL ----------------------------------------------------

def test_describe_reports_seeded_ceiling_intent_and_needs_review(tmp_path):
    _, registration = build(tmp_path=tmp_path)
    policies = registration.provided_ports["permissions.authorizer@1"].policies
    seed_policy_data(policies)
    run_legacy_migration(policies)

    body = call(registration)
    assert set(body) == {"ready", "ceilings", "intents", "needsReview"}
    assert set(body["ceilings"][0]) == CEILING_KEYS
    ceiling = next(c for c in body["ceilings"] if c["policyId"] == "admin")
    assert ceiling["scope"] == "admin"
    assert ceiling["revision"] == 1
    assert ceiling["source"] == "signed-admin"      # trusted provenance, stated
    assert ceiling["signed"] is True
    assert ceiling["maximumExposure"] == "full"
    assert ceiling["effectiveFrom"] == "2020-01-01T00:00:00+00:00"
    assert ceiling["hardDenies"] == [
        {"key": "edit", "pattern": "/etc/*", "action": "deny"}]
    assert ceiling["requireApproval"] == [
        {"key": "bash", "pattern": None, "action": "require-approval"}]
    for entry in ceiling["hardDenies"] + ceiling["requireApproval"]:
        assert set(entry) == ENTRY_KEYS

    assert len(body["intents"]) == 2          # the seeded user intent + the
    intent = next(i for i in body["intents"] if i["intentId"] == "intent-user-1")
    assert set(intent) == INTENT_KEYS
    assert intent["intentId"] == "intent-user-1"
    assert intent["scope"] == "user"
    assert intent["desiredMode"] is None
    assert {rule["key"] for rule in intent["rules"]} == {"read", "bash"}
    for rule in intent["rules"]:
        assert set(rule) == RULE_KEYS

    # the legacy import's non-equivalent findings are real stored review rows
    assert body["needsReview"], "the full-access preset finding must be reported"
    for finding in body["needsReview"]:
        assert set(finding) == REVIEW_KEYS
        assert finding["source"] == "legacy-profile:profile-1"
        assert finding["index"] is None or isinstance(finding["index"], int)
    assert any("full-access" in finding["reason"] for finding in body["needsReview"])


def test_desired_mode_is_reported_as_brand_and_name(tmp_path):
    _, registration = build(tmp_path=tmp_path)
    policies = registration.provided_ports["permissions.authorizer@1"].policies
    policies.store_intent(PermissionIntent.of(
        intent_id="intent-claude-1", revision=1, harness_id="claude-code",
        scope="user", rules=[],
        desired_mode=BrandMode.declare("claude-code", "plan")))
    intent = next(i for i in call(registration)["intents"]
                  if i["intentId"] == "intent-claude-1")
    assert intent["desiredMode"] == {"brand": "claude-code", "name": "plan"}


def test_ready_mirrors_admission_readiness(tmp_path):
    # default composition: no native-evidence source wired -> honest False,
    # derived exactly like the admission port's own `ready`.
    _, registration = build(tmp_path=tmp_path)
    admission = registration.provided_ports[ACP_ADMISSION_PORT]
    assert call(registration)["ready"] is False
    assert call(registration)["ready"] == admission.ready


def test_ready_true_when_native_evidence_is_wired(tmp_path):
    _, registration = build(
        ports={NATIVE_EVIDENCE_PORT: lambda: {"nativeSessionId": "native-1",
                                              "runtimeGeneration": 3}},
        tmp_path=tmp_path)
    admission = registration.provided_ports[ACP_ADMISSION_PORT]
    assert admission.ready is True
    assert call(registration)["ready"] is True


# -- negative proofs ---------------------------------------------------------------------

def test_unwired_repository_answers_not_ready_and_empty_lists():
    body = PolicyDescribe(None).describe({})
    assert body == {"ready": False, "ceilings": [], "intents": [], "needsReview": []}


def test_unverified_ceiling_row_reports_its_source(tmp_path):
    _, registration = build(tmp_path=tmp_path)
    policies = registration.provided_ports["permissions.authorizer@1"].policies
    crafted_ceiling(policies, {
        "policyId": "ghost", "scope": "admin", "revision": 1,
        "source": "unverified", "signed": False,
        "deny": [{"key": "bash", "action": "deny"}], "requireApproval": [],
        "maximumExposure": "full", "effectiveFrom": "2020-01-01T00:00:00+00:00"})
    body = call(registration)
    ghost = next(c for c in body["ceilings"] if c["policyId"] == "ghost")
    # reported WITH its source, so a client cannot mistake it for an
    # enforceable limit; the trusted rows next to it keep theirs.
    assert ghost["source"] == "unverified"
    assert ghost["signed"] is False
    assert all(c["source"] != "unverified"
               for c in body["ceilings"] if c["policyId"] == "admin")


def test_unverified_ceiling_is_never_storeable_or_enforceable(tmp_path):
    _, registration = build(tmp_path=tmp_path)
    policies = registration.provided_ports["permissions.authorizer@1"].policies
    with pytest.raises(PolicyRefusal):
        policies.store_ceiling(PolicyCeiling.unverified("ghost"))
    # the lane's refusal behaviour for the crafted unverified row is unchanged:
    # the enforcement read path still refuses to carry it.
    crafted_ceiling(policies, {
        "policyId": "ghost", "scope": "admin", "revision": 1,
        "source": "unverified", "signed": False, "deny": [], "requireApproval": [],
        "maximumExposure": "full", "effectiveFrom": "2020-01-01T00:00:00+00:00"})
    with pytest.raises(PolicyRefusal):
        policies.ceilings_current()


def test_undeclared_stored_fields_cannot_smuggle_keys(tmp_path):
    _, registration = build(tmp_path=tmp_path)
    policies = registration.provided_ports["permissions.authorizer@1"].policies
    crafted_ceiling(policies, {
        "policyId": "sneaky", "scope": "admin", "revision": 1,
        "source": "signed-admin", "signed": True, "deny": [], "requireApproval": [],
        "maximumExposure": "full", "effectiveFrom": "2020-01-01T00:00:00+00:00",
        "apiKey": "hunter2-never-echoed"})
    with pytest.raises(ValueError) as refused:
        call(registration)
    assert "hunter2" not in str(refused.value)
    assert "apiKey" not in str(refused.value)

    # an oversized pattern cannot ride along either
    with policies.database.transaction() as conn:
        conn.execute("DELETE FROM permissions_policy_ceilings WHERE policy_id='sneaky'")
    crafted_ceiling(policies, {
        "policyId": "huge", "scope": "admin", "revision": 1,
        "source": "signed-admin", "signed": True,
        "deny": [{"key": "bash", "action": "deny", "pattern": "x" * 5000}],
        "requireApproval": [], "maximumExposure": "full",
        "effectiveFrom": "2020-01-01T00:00:00+00:00"})
    with pytest.raises(ValueError):
        call(registration)

    # the same rule holds for intents
    with pytest.raises(PolicyRefusal):
        policies.store_intent_record({
            "intentId": "sneaky-intent", "revision": 1, "harnessId": "pi",
            "scope": "user", "rules": [], "clientSecret": "hunter3"})


def test_host_refuses_unknown_request_param(tmp_path):
    from ordessa_server.plugin_host.host import MethodRegistry
    from ordessa_server.wire.errors import WireError as HostWireError
    from ordessa_server.wire.handlers import WireService

    _, registration = build(tmp_path=tmp_path)
    registry = MethodRegistry()
    service = WireService(server_id_provider=lambda: "srv-test",
                          cursor_secret=b"x" * 32, method_registry=registry)
    registry.register(descriptor(registration))
    with pytest.raises(HostWireError) as refused:
        service.dispatch(POLICY_DESCRIBE_METHOD, {"bogus": 1})
    assert refused.value.family == "INVALID_REQUEST"
    assert "unexpected bogus" in refused.value.message


def test_host_dispatch_serves_the_declared_params_only(tmp_path):
    from ordessa_server.plugin_host.host import MethodRegistry
    from ordessa_server.wire.handlers import WireService

    _, registration = build(tmp_path=tmp_path)
    seed_policy_data(registration.provided_ports["permissions.authorizer@1"].policies)
    registry = MethodRegistry()
    service = WireService(server_id_provider=lambda: "srv-test",
                          cursor_secret=b"x" * 32, method_registry=registry)
    registry.register(descriptor(registration))
    assert service.dispatch(POLICY_DESCRIBE_METHOD, {})["ceilings"]
    body = service.dispatch(POLICY_DESCRIBE_METHOD,
                            {"principal": "user-1", "scope": "admin"})
    assert [c["policyId"] for c in body["ceilings"]] == ["admin"]


def test_describe_mutates_no_rows(tmp_path):
    database, registration = build(tmp_path=tmp_path)
    policies = registration.provided_ports["permissions.authorizer@1"].policies
    seed_policy_data(policies)
    run_legacy_migration(policies)
    before = all_rows(database)
    call(registration)
    call(registration, {"principal": "user-1", "scope": "user"})
    assert all_rows(database) == before       # byte-for-byte the same stored state


def test_scope_filters_entries_and_principal_is_inert(tmp_path):
    _, registration = build(tmp_path=tmp_path)
    policies = registration.provided_ports["permissions.authorizer@1"].policies
    seed_policy_data(policies)
    full = call(registration)
    only_user = call(registration, {"scope": "user"})
    assert only_user["ceilings"] == []                       # the admin ceiling is out
    assert [i["intentId"] for i in only_user["intents"]] == ["intent-user-1"]
    only_admin = call(registration, {"scope": "admin"})
    assert [c["policyId"] for c in only_admin["ceilings"]] == ["admin"]
    assert only_admin["intents"] == []
    # stored policy records carry no principal: naming one never widens the
    # answer and never changes it (it attributes nothing here).
    assert call(registration, {"principal": "someone"}) == full

    from server_plugin_api import WireError
    with pytest.raises(WireError):
        call(registration, {"scope": "banana"})
    with pytest.raises(WireError):
        call(registration, {"principal": "x" * 5000})


def test_availability_reports_unwired_and_unreadable_truthfully(tmp_path):
    unsupported = PolicyDescribe(None).availability()
    assert unsupported[0] is False and unsupported[1]

    _, registration = build(tmp_path=tmp_path)
    method = descriptor(registration)
    assert method.availability() == (True, None)

    database = seeded_database(tmp_path / "second")
    broken = PolicyRepository(database)          # schema never created
    unreadable = PolicyDescribe(broken).availability()
    assert unreadable[0] is False and "UNREADABLE" in unreadable[1]


def test_availability_never_gates_dispatch(tmp_path):
    # order 097: support state and existence are two questions. The handler
    # answers the honest empty body even while availability says unsupported.
    describe = PolicyDescribe(None)
    assert describe.availability()[0] is False
    assert describe.describe({}) == {
        "ready": False, "ceilings": [], "intents": [], "needsReview": []}
