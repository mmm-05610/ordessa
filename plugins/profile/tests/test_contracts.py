"""v2 contract surface (specs/011-z1-profile, PV-03).

Unknown fields, duplicate keys and malformed declarations are refused;
the four value states stay distinguishable; SessionRef is a real canonical
identity; intents/receipts/journal enforce their typed invariants.
"""
from __future__ import annotations

import pytest

from ordessa_profile import (
    Applicability,
    AppliedReceipt,
    ConfigIntent,
    FacetDescriptor,
    ItemDescriptor,
    JournalEntry,
    MechanismPolicy,
    ProfileError,
    SessionRef,
    UNSET,
    ValueDisabled,
    validate_schema_shape,
    validate_value_against_schema,
    value_state,
)


class TestValueStates:
    def test_unset_is_not_none_and_not_false(self):
        assert UNSET is not None
        assert value_state(UNSET) == "unset"
        assert value_state(None) == "explicit"
        assert value_state([]) == "explicit"
        assert value_state(False) == "explicit"
        assert value_state(ValueDisabled()) == "disabled"

    def test_disabled_is_valued_object(self):
        assert ValueDisabled("reason") == ValueDisabled("reason")
        assert ValueDisabled() != ValueDisabled("why")
        assert value_state(ValueDisabled()) == "disabled"

    def test_unset_is_a_singleton(self):
        from ordessa_profile.contracts import _UnsetType
        assert _UnsetType() is UNSET


class TestSchemaSubset:
    def test_unknown_schema_keyword_refused(self):
        with pytest.raises(ProfileError) as exc:
            validate_schema_shape(
                {"type": "string", "format": "ipv4"}, where="x")
        assert exc.value.code == "FACET_INVALID_PROVIDER"

    def test_unknown_type_refused(self):
        with pytest.raises(ProfileError):
            validate_schema_shape({"type": "weird"}, where="x")

    def test_items_requires_array_type(self):
        with pytest.raises(ProfileError):
            validate_schema_shape({"type": "string", "items": {}}, where="x")

    def test_value_validation_rejects_wrong_type(self):
        schema = {"type": "integer", "minimum": 1, "maximum": 10}
        validate_value_against_schema(schema, 5, where="n")
        with pytest.raises(ProfileError) as exc:
            validate_value_against_schema(schema, "5", where="n")
        assert exc.value.code == "FACET_VALUE_INVALID"
        assert exc.value.item == "n"

    def test_enum_and_bounds(self):
        schema = {"type": "string", "enum": ["a", "b"]}
        validate_value_against_schema(schema, "a", where="e")
        with pytest.raises(ProfileError):
            validate_value_against_schema(schema, "c", where="e")
        with pytest.raises(ProfileError):
            validate_value_against_schema(
                {"type": "array", "minItems": 2}, ["x"], where="arr")

    def test_null_only_when_allowed(self):
        with pytest.raises(ProfileError):
            validate_value_against_schema({"type": "string"}, None, where="s")
        validate_value_against_schema(
            {"type": "string", "allowNull": True}, None, where="s")


class TestDescriptors:
    def test_duplicate_item_ids_refused(self):
        with pytest.raises(ProfileError) as exc:
            FacetDescriptor(
                facet_id="demo", api_major=2, schema_version="1.0.0",
                label="demo",
                item_descriptors=(
                    ItemDescriptor(item_id="a", value_schema={"type": "string"}),
                    ItemDescriptor(item_id="a", value_schema={"type": "string"}),
                ))
        assert exc.value.code == "FACET_INVALID_PROVIDER"

    def test_invalid_facet_or_item_ids_refused(self):
        with pytest.raises(ProfileError):
            FacetDescriptor(facet_id="Bad Id", api_major=2,
                            schema_version="1", label="x")
        with pytest.raises(ProfileError):
            ItemDescriptor(item_id="a b", value_schema={"type": "string"})

    def test_unknown_effect_or_sensitivity_refused(self):
        with pytest.raises(ProfileError):
            ItemDescriptor(item_id="a", value_schema={"type": "string"},
                           effect="magic")
        with pytest.raises(ProfileError):
            ItemDescriptor(item_id="a", value_schema={"type": "string"},
                           sensitivity="secret")

    def test_default_must_match_schema(self):
        with pytest.raises(ProfileError):
            ItemDescriptor(item_id="a", value_schema={
                "type": "integer", "default": "many"})

    def test_applicability_unknown_never_supported(self):
        assert Applicability.UNKNOWN.value == "unknown"
        assert Applicability.UNKNOWN != Applicability.SUPPORTED


class TestSessionRef:
    def test_same_native_key_in_different_realms_are_distinct(self):
        a = SessionRef(realm="alpha", harness_id="pi",
                       native_session_key="n-1", session_uid="u-1")
        b = SessionRef(realm="beta", harness_id="pi",
                       native_session_key="n-1", session_uid="u-2")
        assert a != b
        assert a.routing_key() != b.routing_key()

    def test_empty_fields_refused(self):
        with pytest.raises(ProfileError):
            SessionRef(realm="", harness_id="pi",
                       native_session_key="n", session_uid="u")

    def test_legacy_uid_prefix_is_deterministic(self):
        ref = SessionRef.legacy("S", harness_id="pi")
        assert ref.session_uid == "legacy:S"
        assert ref.realm == "local"


class TestIntentsReceiptsJournal:
    def test_set_intent_requires_value_reset_forbids_it(self):
        with pytest.raises(ProfileError):
            ConfigIntent(facet_id="f", item_id="i", op="set",
                         native_key="f.i", source="profile@1")
        with pytest.raises(ProfileError):
            ConfigIntent(facet_id="f", item_id="i", op="reset",
                         native_key="f.i", source="profile@1", value="x")
        intent = ConfigIntent(facet_id="f", item_id="i", op="set",
                              native_key="f.i", source="profile@1", value=0)
        assert intent.value == 0  # an explicit zero is a real value

    def test_receipt_refuses_legacy_evidence(self):
        with pytest.raises(ProfileError) as exc:
            AppliedReceipt(
                operation_id="op", session_ref=SessionRef(
                    realm="r", harness_id="h", native_session_key="n",
                    session_uid="u"),
                runtime_generation="g", config_digest="sha256:x",
                profile_id="p", profile_revision=1, overlay_revision=None,
                policy_revision=1, provider_generations={},
                evidence_kind="legacy-unverified", confirmed_at="t")
        assert exc.value.code == "LEGACY_RECEIPT_UNVERIFIED"

    def test_journal_entry_state_validated(self):
        ref = SessionRef(realm="r", harness_id="h", native_session_key="n",
                         session_uid="u")
        with pytest.raises(ProfileError):
            JournalEntry(operation_id="op", session_ref=ref,
                         state="applied", profile_id="p",
                         profile_revision=1, plan_digest="sha256:x")

    def test_receipt_public_projection_has_no_secret_fields(self):
        import re
        receipt = AppliedReceipt(
            operation_id="op", session_ref=SessionRef(
                realm="r", harness_id="h", native_session_key="n",
                session_uid="u"),
            runtime_generation="g", config_digest="sha256:x",
            profile_id="p", profile_revision=1, overlay_revision=None,
            policy_revision=1, provider_generations={"f": 1},
            evidence_kind="port-confirmed", confirmed_at="t")
        blob = str(receipt.as_public_dict())
        assert not re.search(
            r"(secret|token|api[_-]?key|password|credential_value)", blob,
            re.I)


class TestMechanismPolicy:
    def test_policy_carries_no_permissions_or_secrets(self):
        policy = MechanismPolicy(realm="local", revision=3,
                                 facet_enabled={"f": False})
        assert policy.facet_enabled_for("f") is False
        assert policy.facet_enabled_for("unknown") is True  # default-enabled
        assert policy.override_writes_allowed("f") is True
        blob = str(policy)
        assert "permission" not in blob

    def test_invalid_policy_input_refused(self):
        with pytest.raises(ProfileError):
            MechanismPolicy(realm="r", revision=0)
        with pytest.raises(ProfileError):
            MechanismPolicy(realm="r", revision=1, facet_enabled={"f": "yes"})
        with pytest.raises(ProfileError):
            MechanismPolicy(realm="r", revision=1,
                            allow_user_override_writes={"f": 1})

    def test_per_facet_override_gate(self):
        policy = MechanismPolicy(
            realm="r", revision=1, allow_user_override_writes_global=False)
        assert policy.override_writes_allowed() is False
        assert policy.override_writes_allowed("f") is False
