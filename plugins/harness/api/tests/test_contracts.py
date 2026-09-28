import unittest
import json
import copy
from dataclasses import asdict

from ordessa_harness_api import (
    ApplicationTarget, Assessment, BindSecret, ConfigurationCapability,
    ContractError, DesiredFragment, ErrorCode, FieldPath, IntentSet,
    IntentSource, ResetField, SetField, TargetHandle, ValueSchema,
    VersionRange, ResumeRequest, RuntimeConfirmed, RuntimeRefused,
    RuntimeUnknown, ReconfigurationDecision, LaunchPlan, ActionDescriptor,
    TargetDescriptor, Plan, Confirmed, Refused, Unknown, OperationRecord,
    RuntimeAdapterDescriptor, ConfigurationCapabilities, closed_object,
    InvokeAction, Installation, ConfigurationAdapterDescriptor, FieldClaim,
)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.source = IntentSource("model-provider", "primary", "v1")
        self.target = TargetHandle("opaque-1", 2)

    def test_closed_schema(self):
        schema = closed_object(model=ValueSchema("string"))
        self.assertEqual(schema.validate({"model": "x"}), {"model": "x"})
        for bad in ({"model": "x", "surprise": True}, {"model": 3}, {}, {"model": object()}):
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                schema.validate(bad)

    def test_discriminated_intents_and_secret_boundary(self):
        set_intent = SetField(self.source, self.target, FieldPath(("model", "name")), {"id": "x"})
        reset = ResetField(self.source, self.target, FieldPath(("model", "name")), "remove-key")
        secret = BindSecret(self.source, self.target, "api", "secret-ref-1")
        self.assertEqual([x.kind for x in IntentSet((set_intent, reset, secret)).intents],
                         ["set-field", "reset-field", "bind-secret"])
        for bad in ({"api_key": "plaintext"}, object(), float("nan")):
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                SetField(self.source, self.target, FieldPath(("x",)), bad)
        with self.assertRaises(ContractError):
            IntentSet((object(),))
        with self.assertRaises(ContractError):
            FieldPath(("x/y",))
        with self.assertRaises(ContractError):
            ResetField(self.source, self.target, FieldPath(("x",)), "ignore")

    def test_supported_unsupported_unknown_are_distinct(self):
        self.assertEqual(Assessment("supported").status, "supported")
        self.assertEqual(Assessment("unknown", reason="version absent").status, "unknown")
        with self.assertRaises(ContractError):
            Assessment("unknown")
        self.assertIsNone(VersionRange((1, 0, 0)).contains(None))
        self.assertFalse(VersionRange((1, 0, 0), (1, 9, 9)).contains((2, 0, 0)))
        with self.assertRaises(ContractError):
            ConfigurationCapability("model", "pi", None, None, "acp", "session", "set", "unsupported")

    def test_application_identity_and_reset(self):
        target = ApplicationTarget("server", "session", "channel", 4)
        self.assertEqual(target.runtime_generation, 4)
        with self.assertRaises(ContractError):
            ApplicationTarget("server", "session", "", 4)
        with self.assertRaises(ContractError):
            DesiredFragment("facet", "item", "v1", "ref", "revision", "reset", "old")
        self.assertEqual(ErrorCode.STALE_PLAN.value, "stale-plan")

    def test_runtime_lifecycle_results_and_resume(self):
        request = ResumeRequest("old-instance", "native-session", 3)
        self.assertEqual(request.method, "resume")
        self.assertEqual(RuntimeConfirmed("new-instance", "native-session", 4, "proof").kind, "confirmed")
        self.assertEqual(RuntimeRefused(ErrorCode.RESUME_UNAVAILABLE, "missing").kind, "refused")
        self.assertEqual(RuntimeUnknown("old-instance", ("spawned",), ("read-back",)).kind, "unknown")
        self.assertEqual(ReconfigurationDecision("restart-resume", ("old-instance",)).mode, "restart-resume")
        with self.assertRaises(ContractError):
            ResumeRequest("old-instance", "", 3)
        with self.assertRaises(ContractError):
            ResumeRequest("old-instance", "native-session", -1)
        with self.assertRaises(TypeError):
            ResumeRequest("old-instance", "native-session", 3, method="session/new")
        with self.assertRaises(ContractError):
            ReconfigurationDecision("unsupported", ())

    def test_runtime_descriptors_reject_invalid_structure(self):
        for constructor in (
            lambda: TargetDescriptor(self.target, "arbitrary", "json", "session"),
            lambda: TargetDescriptor(self.target, "environment", "json", "session"),
            lambda: ActionDescriptor("x", "v1", ValueSchema("object"), ValueSchema("object"), "global", "none", False),
            lambda: LaunchPlan(self.target, "", (), None, "snapshot"),
            lambda: LaunchPlan(self.target, "executable", "not-a-tuple", None, "snapshot"),
            lambda: RuntimeConfirmed("", "native", 1, "proof"),
            lambda: RuntimeConfirmed("instance", "", 1, "proof"),
            lambda: RuntimeConfirmed("instance", "native", -1, "proof"),
            lambda: RuntimeUnknown("instance", (), ()),
        ):
            with self.subTest(constructor=constructor), self.assertRaises(ContractError):
                constructor()

    def test_secret_fields_and_schema_shape_rejected(self):
        for bad in (
            lambda: SetField(self.source, self.target, FieldPath(("apiKey",)), "plaintext"),
            lambda: SetField(self.source, self.target, FieldPath(("model",)), {"accessToken": "plaintext"}),
            lambda: ValueSchema("object", properties=(("x", "not-a-schema"),), required=("x",)),
            lambda: ValueSchema("array", items="not-a-schema"),
        ):
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                bad()
        with self.assertRaises(ContractError):
            ValueSchema("integer", enum=(True,)).validate(1)
        self.assertEqual(ValueSchema("integer", enum=(1,)).validate(1), 1)

    def test_c4_states_reject_invalid_identity_and_status(self):
        target = ApplicationTarget("server", "session", "channel", 1)
        for bad in (
            lambda: Plan("", target, "digest", "before", "native", 1, "auth", "secret", "expiry"),
            lambda: Plan("plan", target, "digest", "before", "native", -1, "auth", "secret", "expiry"),
            lambda: Confirmed("op", "revision", "", 1, "proof", ()),
            lambda: Confirmed("op", "revision", "native", -1, "proof", ()),
            lambda: Refused("stale-plan", (), True),
            lambda: Unknown("op", "unrecognized", (), ("check",), "query"),
            lambda: Unknown("op", "applying", (), (), "query"),
            lambda: OperationRecord("op", "key", target, Confirmed("different", "rev", "native", 1, "proof", ())),
        ):
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                bad()

    def test_intent_payload_is_a_deep_read_only_json_snapshot(self):
        original = {"model": ["first", {"name": "second"}]}
        intent = SetField(self.source, self.target, FieldPath(("model",)), original)
        original["model"].append("late")
        self.assertEqual(json.loads(json.dumps(intent.typed_value)),
                         {"model": ["first", {"name": "second"}]})
        self.assertEqual(asdict(intent)["typed_value"],
                         {"model": ["first", {"name": "second"}]})
        ordinary_read = intent.typed_value
        ordinary_read["api_key"] = "plaintext"
        ordinary_read["model"].append("late")
        ordinary_read["model"][1]["name"] = "changed"
        base_method_read = intent.typed_value
        dict.__setitem__(base_method_read, "token", "plaintext")
        list.append(base_method_read["model"], "late")
        self.assertEqual(intent.typed_value, {"model": ["first", {"name": "second"}]})
        self.assertEqual(copy.deepcopy(intent).typed_value, intent.typed_value)
        action = InvokeAction(self.source, "reload", "v1", {"options": ["safe"]}, "observed")
        list.append(action.typed_payload["options"], "late")
        self.assertEqual(action.typed_payload, {"options": ["safe"]})
        fragment = DesiredFragment("facet", "item", "v1", "ref", "rev", "set",
                                   {"options": ["safe"]})
        list.append(fragment.value["options"], "late")
        self.assertEqual(fragment.value, {"options": ["safe"]})
        self.assertEqual(json.loads(json.dumps(asdict(fragment)["value"])),
                         {"options": ["safe"]})

    def test_intent_set_and_aliases_cannot_change_after_validation(self):
        intent = SetField(self.source, self.target, FieldPath(("model",)), "x")
        source_list = [intent]
        sealed = IntentSet(source_list)
        source_list.append(object())
        self.assertEqual(sealed.intents, (intent,))
        with self.assertRaises(AttributeError):
            sealed.intents.append(object())
        aliases = ["legacy"]
        descriptor = RuntimeAdapterDescriptor("adapter", "v1", "pi", aliases,
                                              VersionRange((1, 0, 0)))
        aliases.append("pi")
        self.assertEqual(descriptor.aliases, ("legacy",))
        with self.assertRaises(ContractError):
            RuntimeAdapterDescriptor("adapter", "v1", "pi", ("pi",),
                                     VersionRange((1, 0, 0)))
        with self.assertRaises(ContractError):
            RuntimeAdapterDescriptor("adapter", "v1", "pi", ("PI",),
                                     VersionRange((1, 0, 0)))
        with self.assertRaises(ContractError):
            IntentSet((object(),))

    def test_nested_dto_members_are_validated_at_construction(self):
        invalid = (
            lambda: SetField("owner", self.target, FieldPath(("model",)), "x"),
            lambda: SetField(self.source, "target", FieldPath(("model",)), "x"),
            lambda: Plan("plan", "target", "digest", "before", "native", 1,
                         "auth", "secret", "expiry"),
            lambda: ConfigurationCapabilities("target", [object()]),
            lambda: RuntimeAdapterDescriptor("adapter", "v1", "pi", (), "range"),
        )
        for make in invalid:
            with self.subTest(make=make), self.assertRaises(ContractError):
                make()

    def test_schema_snapshot_cannot_change_accepted_fields_after_construction(self):
        properties = [["model", ValueSchema("string")]]
        required = ["model"]
        schema = ValueSchema("object", properties=properties, required=required)
        properties.append(["rogue", ValueSchema("boolean")])
        required.clear()
        self.assertEqual(schema.validate({"model": "x"}), {"model": "x"})
        with self.assertRaises(ContractError):
            schema.validate({"model": "x", "rogue": True})
        with self.assertRaises(ContractError):
            schema.validate({})
        self.assertEqual(schema.properties, (("model", ValueSchema("string")),))
        self.assertEqual(schema.required, ("model",))

    def test_version_and_pending_checks_are_immutable_snapshots(self):
        native = [1, 2, 3]
        adapter = [4, 5, 6]
        installation = Installation("pi", native, adapter, "evidence")
        native[0] = 9
        adapter[0] = 9
        self.assertEqual((installation.native_version, installation.adapter_version),
                         ((1, 2, 3), (4, 5, 6)))
        effects = ["spawned"]
        pending = ["read-back"]
        unknown = RuntimeUnknown("instance", effects, pending)
        effects.append("confirmed")
        pending.clear()
        self.assertEqual((unknown.observed_effects, unknown.pending_checks),
                         (("spawned",), ("read-back",)))
        with self.assertRaises(AttributeError):
            unknown.pending_checks.append("later")

    def test_public_identity_fields_reject_non_strings(self):
        invalid = (
            lambda: DesiredFragment(7, "item", "v1", "business", "revision", "set", "x"),
            lambda: DesiredFragment("facet", "item", "v1", 7, "revision", "set", "x"),
            lambda: ResumeRequest(7, "native", 1),
            lambda: ResumeRequest("instance", 7, 1),
            lambda: ConfigurationAdapterDescriptor("a", "v1", "facet", "v1", "pi",
                VersionRange((1, 0, 0)), VersionRange((1, 0, 0)), ["entry"],
                ValueSchema("string"), [FieldClaim("file", "target", ("x",))]),
        )
        for make in invalid[:4]:
            with self.subTest(make=make), self.assertRaises(ContractError):
                make()
        descriptor = invalid[4]()
        self.assertEqual(descriptor.entries, ("entry",))
        self.assertIsInstance(descriptor.claims, tuple)


if __name__ == "__main__":
    unittest.main()
