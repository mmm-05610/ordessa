"""Owner-scoped live model runtime for the existing C4 application service.

Only native actions are admitted. No configuration files are materialized and
no global state is used. Installation evidence is injected by trusted launch
composition; a request cannot choose its version or publication authority.
"""
from pathlib import Path
from uuid import uuid4

from ordessa_harness_api import ActionDescriptor, Installation, ValueSchema
from ...application.configuration_service import NativeReadback, RuntimeSnapshot
from ...materialization import MergeAuthority
from ...server_acp.native_action_executor import NativeSessionActionExecutor, configuration_digest
from .live_context import NativeLiveModelContext


INPUT = ValueSchema("object", properties=(("configId", ValueSchema("string", enum=("model",))),
    ("value", ValueSchema("string"))), required=("configId", "value"))
RESULT = ValueSchema("object", properties=(("currentValue", ValueSchema("string")),
    ("expectedValue", ValueSchema("string"))), required=("currentValue", "expectedValue"))
ACTION = ActionDescriptor("acp.session.set-config-option", "1", INPUT, RESULT,
                          "session", "read-back", False)


class NativeLiveModelRuntime:
    harness_id = None
    native_version = None
    context_class = NativeLiveModelContext

    def __init__(self, registry, owners, *, target, installation: Installation,
                 private_root: Path, publication_revision: str):
        if (not isinstance(installation, Installation) or installation.harness_id != self.harness_id
            or installation.native_version != self.native_version
            or not isinstance(publication_revision, str) or not publication_revision):
            raise ValueError("Verified pinned native installation and publication required")
        self.registry, self.owners, self.target = registry, owners, target
        self.installation, self.private_root = installation, Path(private_root)
        self.publication_revision = publication_revision
        self._executor = None
        self._expected_value = None
        self._captured_digest = None

    def capture(self, target):
        if target != self.target:
            raise ValueError("Foreign native model target")
        native = self.owners.readback(target)
        channel = self.registry.get(native.owner.connection_id)
        if channel is None or channel.harness_id != self.harness_id:
            raise ValueError("Matching native owner unavailable")
        digest = configuration_digest(native.config_options)
        self._captured_digest = digest
        context = self.context_class((), self.installation, "acp", "session",
            self.harness_id + "-native-catalog:" + digest, native)
        return RuntimeSnapshot(target, context, MergeAuthority((), (ACTION,), "session"),
            {}, {}, self.private_root, {}, digest, self.installation.evidence_ref,
            target.runtime_generation, self.publication_revision, "native-auth-unchanged")

    def preflight(self, batch):
        if batch.target != self.target or len(batch.invocations) != 1 or self._captured_digest is None:
            raise ValueError("One captured exact native model action required")
        # Both stage-time and immediately-before-effects validation use the
        # same live owner and before digest; C4 separately fences plan capture.
        executor = NativeSessionActionExecutor(self.registry, self.owners, target=self.target,
            expected_configuration_digest=self._captured_digest, harness_id=self.harness_id)
        ACTION.input_schema.validate(batch.invocations[0].intent.typed_payload)
        executor.preflight(batch)
        self._executor = executor

    def execute(self, operation_id, batch):
        if self._executor is None or batch.target != self.target or len(batch.invocations) != 1:
            raise ValueError("Native action was not preflighted")
        ACTION.input_schema.validate(batch.invocations[0].intent.typed_payload)
        receipt = self._executor.execute(operation_id, batch)
        self._expected_value = batch.invocations[0].intent.typed_payload["value"]
        return receipt

    def activate_generation(self, *args):
        raise ValueError("Live model application never materializes files")

    def observe(self, target):
        if target != self.target or self._executor is None or self._executor.last_receipt is None:
            raise ValueError("No operation-bound native receipt")
        native = self.owners.readback(target)
        selector = [item for item in native.config_options if item.get("id") == "model"]
        if len(selector) != 1 or not isinstance(selector[0].get("currentValue"), str):
            raise ValueError("Native model readback unavailable")
        digest = configuration_digest(native.config_options)
        return NativeReadback(target, native.owner.native_session_id, digest,
            {"currentValue": selector[0]["currentValue"], "expectedValue": self._expected_value}, (),
            self.harness_id + "-independent-query:" + uuid4().hex, ("session-model",), self._executor.last_receipt)
