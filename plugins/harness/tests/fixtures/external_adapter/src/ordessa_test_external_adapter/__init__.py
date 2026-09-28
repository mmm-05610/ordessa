"""Controlled third-party fixture: only public contract imports, no Harness internals."""
from __future__ import annotations

from ordessa_harness_api import (
    Assessment, ConfigurationAdapterDescriptor, FieldClaim, FieldPath,
    Installation, IntentSet, IntentSource, LaunchPlan, Match, Mismatch,
    ReconfigurationDecision, ResumeRequest, RuntimeAdapterDescriptor,
    RuntimeConfirmed, RuntimeRefused, RuntimeUnknown, SetField, TargetDescriptor,
    TargetHandle, ValueSchema, VerificationUnknown, VersionRange, ErrorCode,
)
from server_plugin_api import (
    Contribution, ContributionBatch, ServerPluginDescriptor,
    ServerPluginRegistration,
)

OWNER = "test.external-adapter"
RUNTIME_POINT = "harness.runtime-adapters"
CONFIGURATION_POINT = "harness.configuration-adapters"


class ControlledConfigurationAdapter:
    descriptor = ConfigurationAdapterDescriptor(
        "test.external.model", "v1", "model", "v1", "test-external",
        VersionRange((1, 0, 0)), VersionRange((1, 0, 0)), ("acp",),
        ValueSchema("object", properties=(("model", ValueSchema("string")),), required=("model",)),
        (FieldClaim("file", "external-config", ("model",)),),
    )

    def __init__(self):
        self.compile_calls = 0

    def assess(self, context, request):
        return Assessment("supported", evidence_ref="fixture:controlled")

    def compile(self, context, before, desired):
        self.compile_calls += 1
        payload = self.descriptor.payload_schema.validate(desired)
        target = next(target for target in context.targets if target.kind == "file")
        return IntentSet((SetField(
            IntentSource("model", "fixture-selection", "v1"), target.handle,
            FieldPath(("model",)), payload["model"],
        ),))

    def verify(self, context, observed):
        return VerificationUnknown("fixture has no native readback")


class ControlledRuntimeAdapter:
    """A synthetic state machine behind the public RuntimeAdapter surface.

    It starts no process and makes no claim about a native model. Its explicit
    state and observation switch make Confirmed, Refused and Unknown testable.
    """

    descriptor = RuntimeAdapterDescriptor(
        "test.external.runtime", "v1", "test-external", (), VersionRange((1, 0, 0)))
    target = TargetHandle("test.external.instance", 1)

    def __init__(self):
        self.calls = []
        self._prepared = None
        self._instances = {}
        self._next_generation = 1
        self.uncertain_start = False
        self.readback_ready = False

    def describe_installation(self):
        self.calls.append("describe_installation")
        return Installation("test-external", (1, 0, 0), (1, 0, 0), "fixture:installed")

    def describe_targets(self):
        self.calls.append("describe_targets")
        return (TargetDescriptor(self.target, "file", "json", "instance", (("model",),)),)

    def describe_actions(self):
        self.calls.append("describe_actions")
        return ()

    def prepare_launch(self, request):
        self.calls.append("prepare_launch")
        if request.target != self.target:
            return RuntimeRefused(ErrorCode.TARGET_CONFLICT, "fixture target changed")
        self._prepared = LaunchPlan(request.target, "fixture:in-memory-runtime", (), None,
                                    request.configuration_snapshot_ref)
        return self._prepared

    def start(self, launch_plan):
        self.calls.append("start")
        if launch_plan != self._prepared or self._prepared is None:
            return RuntimeRefused(ErrorCode.STALE_PLAN, "fixture launch was not prepared")
        if any(item["live"] for item in self._instances.values()):
            return RuntimeRefused(ErrorCode.BUSY, "fixture runtime already started")
        generation = self._next_generation
        self._next_generation += 1
        instance_ref = f"fixture:instance:{generation}"
        self._instances[instance_ref] = {"generation": generation, "live": True,
                                         "native": f"fixture:native:{generation}",
                                         "uncertain": self.uncertain_start}
        self._prepared = None
        if self.uncertain_start:
            return RuntimeUnknown(instance_ref, ("fixture:allocated",), ("fixture:readback",))
        return self._confirmed(instance_ref, "fixture:started")

    def connect(self, instance_ref):
        self.calls.append("connect")
        item = self._instances.get(instance_ref)
        if item is None or not item["live"]:
            return RuntimeRefused(ErrorCode.RESUME_UNAVAILABLE, "fixture instance unavailable")
        if item["uncertain"] and not self.readback_ready:
            return RuntimeUnknown(instance_ref, ("fixture:allocated",), ("fixture:readback",))
        item["uncertain"] = False
        return self._confirmed(instance_ref, "fixture:connected")

    def close(self, instance_ref):
        self.calls.append("close")
        item = self._instances.get(instance_ref)
        if item is None or not item["live"]:
            return RuntimeRefused(ErrorCode.RESUME_UNAVAILABLE, "fixture instance unavailable")
        if item["uncertain"] and not self.readback_ready:
            return RuntimeUnknown(instance_ref, ("fixture:allocated",), ("fixture:readback",))
        item["live"] = False
        return self._confirmed(instance_ref, "fixture:closed")

    def reconcile(self, instance_ref):
        self.calls.append("reconcile")
        item = self._instances.get(instance_ref)
        if item is None:
            return RuntimeRefused(ErrorCode.RESUME_UNAVAILABLE, "fixture instance unavailable")
        if item["uncertain"] and not self.readback_ready:
            return RuntimeUnknown(instance_ref, ("fixture:allocated",), ("fixture:readback",))
        item["uncertain"] = False
        return self._confirmed(instance_ref, "fixture:observed")

    def prepare_reconfiguration(self, plan_id):
        self.calls.append("prepare_reconfiguration")
        return ReconfigurationDecision("unsupported", (), "fixture has no reconfiguration")

    def resume(self, request: ResumeRequest):
        self.calls.append("resume")
        item = self._instances.get(request.instance_ref)
        if (item is None or not item["live"] or item["generation"] != request.expected_generation
                or item["native"] != request.expected_native_session_identity):
            return RuntimeRefused(ErrorCode.RESUME_UNAVAILABLE, "fixture resume identity changed")
        return self.connect(request.instance_ref)

    def _confirmed(self, instance_ref, evidence):
        item = self._instances[instance_ref]
        return RuntimeConfirmed(instance_ref, item["native"], item["generation"], evidence)


class ExternalAdapterPlugin:
    runtime_descriptor = ControlledRuntimeAdapter.descriptor

    def __init__(self):
        self.runtime_adapter = ControlledRuntimeAdapter()
        self.configuration_adapter = ControlledConfigurationAdapter()
        self.build_count = 0

    def descriptor(self):
        return ServerPluginDescriptor(OWNER, "Controlled external adapter", "1")

    def build(self, context):
        self.build_count += 1
        return ServerPluginRegistration(contributions=ContributionBatch((
            Contribution(RUNTIME_POINT, "v1", self.runtime_adapter, required=True),
            Contribution(CONFIGURATION_POINT, "v1", self.configuration_adapter, required=True),
        )))


class ReadbackConfigurationAdapter(ControlledConfigurationAdapter):
    """Fixture confirms only the observed native value, never a plan value."""

    def verify(self, context, observed):
        if isinstance(observed, dict) and observed.get("model") == "fixture-model":
            return Match("fixture:native-readback")
        return Mismatch("native model did not match fixture selection")


class ReadbackExternalAdapterPlugin(ExternalAdapterPlugin):
    def __init__(self):
        super().__init__()
        self.configuration_adapter = ReadbackConfigurationAdapter()
