"""T05 — the C3 seam is BOUND: compiled fields become real Harness intents.

The `harness-api` checkpoint (record
``specs/011-plugin-rollout/checkpoints/harness-api.json``, status READY,
implementation ``61966e3118``, published ``d3f026904e`` and merged into this
lane as ``953fb915eb``) makes ``ordessa_harness_api`` a published, consumable
contract, so the seam that the foundation lane left explicitly UNBOUND is bound
here for real:

* ``CompiledFieldIntent.to_harness_c3()`` returns the platform's own
  ``SetField`` / ``ResetField`` / ``InvokeAction`` object, attributed with a
  real ``IntentSource("sandbox.native-configuration", item_id, "1")`` over the
  server-issued ``TargetHandle`` and addressed by a real ``FieldPath``;
* ``CompiledIntent.to_harness_c3()`` assembles them into a real ``IntentSet``
  — the type ``ConfigurationAdapter.compile`` is declared to return;
* the *kind* vocabulary is read off the platform classes
  (``HARNESS_C3_INTENT_KINDS``), and the former local mirror
  ``SandboxNativeConfigurationAdapter`` (plus ``AssessReport``/``VerifyResult``)
  is deleted — one vocabulary, imported from the platform (``surface.py``
  conforms to ``ConfigurationAdapter``).

The obsolete tripwire lives here instead: a test now FAILS if the checkpoint
record is absent, is not READY, or names a different implementation SHA — a
non-READY or PARTIAL record is not consumable, and binding to a moving contract
silently is exactly what the rollout evidence rule forbids.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from _sandbox_adapters_helpers import (
    CLAUDE_TARGET,
    CODEX_TARGET,
    PI_TARGET,
    authorized_facts,
    claude_intent,
    codex_intent,
    permissive_ceiling,
    pi_intent,
    target_handle,
)
from ordessa_harness_api import (
    ConfigurationAdapter,
    ConfigurationAdapterDescriptor,
    FieldPath,
    IntentSet,
    IntentSource,
    InvokeAction,
    Match,
    Mismatch,
    ResetField,
    SetField,
    TargetHandle,
    VerificationUnknown,
)

from ordessa_sandbox_adapters import (
    HARNESS_C3_INTENT_KINDS,
    ClaudeSandboxAdapter,
    CodexSandboxAdapter,
    CompiledFieldIntent,
    CompiledIntent,
    PiSandboxAdapter,
    PiSandboxExtensionEvidence,
    SANDBOX_FACET_ID,
    SANDBOX_FACET_SCHEMA_VERSION,
    sandbox_item_id,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
CHECKPOINT_RECORD = (REPO_ROOT / "specs/011-plugin-rollout/checkpoints"
                     / "harness-api.json")
CHECKPOINT_REF = "refs/heads/codex/011-harness-api-ready"
CHECKPOINT_IMPLEMENTATION_SHA = "61966e31189a911c295faba30a07316c44041f47"
CHECKPOINT_PUBLICATION_SHA = "d3f026904ead6c7ce58df26f2536175ce6179de7"

#: the C3 symbols this package binds, all of which the record must publish
BOUND_C3_SYMBOLS = {"IntentSource", "TargetHandle", "FieldPath", "SetField",
                    "ResetField", "InvokeAction", "BindSecret", "MountContent",
                    "ContentRef", "RemoveOwnedContent", "Intent", "IntentSet",
                    "JsonValue"}

#: the C2/C4 result vocabulary this package now imports instead of mirroring
BOUND_CONTRACT_SYMBOLS = {"ConfigurationAdapter", "ConfigurationAdapterDescriptor",
                          "FieldClaim", "Assessment", "Verification", "Match",
                          "Mismatch", "VerificationUnknown", "AdapterContext",
                          "AdapterRefusal", "VersionRange", "TargetDescriptor",
                          "ActionDescriptor"}


def _record() -> dict:
    assert CHECKPOINT_RECORD.is_file(), (
        f"the C3 binding is only valid while the harness-api checkpoint record "
        f"exists: {CHECKPOINT_RECORD} is absent — re-unbind the seam")
    return json.loads(CHECKPOINT_RECORD.read_text(encoding="utf-8"))


# ------------------------------------------------- checkpoint presence/compat
def test_harness_api_checkpoint_record_is_present_and_ready():
    record = _record()
    assert record["name"] == "harness-api"
    assert record["producer"] == "c0"
    # a PARTIAL or absent record is NOT consumable: the binding requires READY
    assert record["status"] == "READY", (
        f"harness-api record status is {record['status']!r}; only READY is "
        "consumable and this package binds it")
    assert record["implementationSha"] == CHECKPOINT_IMPLEMENTATION_SHA, (
        "the bound contract moved: re-verify the C3 surface before binding to a "
        f"new SHA (record says {record['implementationSha']!r})")


def test_harness_api_checkpoint_ref_exists_and_is_an_ancestor_of_head():
    sha = subprocess.run(["git", "rev-parse", "--verify", CHECKPOINT_REF],
                         cwd=REPO_ROOT, capture_output=True, text=True)
    assert sha.returncode == 0, (
        f"{CHECKPOINT_REF} is absent — the C3 binding would be unbacked")
    assert sha.stdout.strip() == CHECKPOINT_PUBLICATION_SHA
    for candidate in (CHECKPOINT_IMPLEMENTATION_SHA, CHECKPOINT_PUBLICATION_SHA):
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", candidate, "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True)
        assert ancestor.returncode == 0, (
            f"{candidate} is not an ancestor of HEAD: this tree does not really "
            f"carry the checkpoint it binds ({ancestor.stderr.strip()})")


def test_every_bound_c3_symbol_is_a_recorded_public_export():
    exports = set(_record()["publicExports"]["harnessApiExports"])
    assert BOUND_C3_SYMBOLS <= exports, sorted(BOUND_C3_SYMBOLS - exports)
    assert BOUND_CONTRACT_SYMBOLS <= exports, sorted(BOUND_CONTRACT_SYMBOLS - exports)


def test_bound_symbols_are_the_published_module_objects():
    """Module identity, not a same-named copy: the classes the seam constructs
    are the ones ``ordessa_harness_api`` exports."""
    import ordessa_harness_api
    for name in BOUND_C3_SYMBOLS | BOUND_CONTRACT_SYMBOLS:
        assert hasattr(ordessa_harness_api, name), name
    from ordessa_sandbox_adapters import seam
    assert seam.SetField is ordessa_harness_api.SetField
    assert seam.TargetHandle is ordessa_harness_api.TargetHandle
    assert seam.IntentSet is ordessa_harness_api.IntentSet


# --------------------------------------------------------------- the binding
def _codex_fields():
    adapter = CodexSandboxAdapter()
    result = adapter.compile(codex_intent(), target_handle(CODEX_TARGET),
                             (permissive_ceiling(),))
    assert isinstance(result, CompiledIntent), result
    return result


def _claude_fields():
    adapter = ClaudeSandboxAdapter()
    result = adapter.compile(claude_intent(), target_handle(CLAUDE_TARGET),
                             (permissive_ceiling(brand="claude-code"),))
    assert isinstance(result, CompiledIntent), result
    return result


def _pi_fields():
    ext = PiSandboxExtensionEvidence.of(
        extension_id="sandbox-ext", loaded=True, observed_native_version="2.0")
    result = PiSandboxAdapter().compile(
        pi_intent(), target_handle(PI_TARGET),
        (permissive_ceiling(brand="pi"),),
        authorized=authorized_facts(pi_sandbox_extension=ext))
    assert isinstance(result, CompiledIntent), result
    return result


def test_codex_fields_bind_real_platform_setfield_objects():
    compiled = _codex_fields()
    handle = target_handle(CODEX_TARGET)
    bound = compiled.to_harness_c3()
    assert isinstance(bound, IntentSet)
    assert len(bound.intents) == len(compiled.intents)
    for intent in bound.intents:
        assert isinstance(intent, SetField)
        # the same server-issued handle is carried, never a copy of a string
        assert intent.target == handle
        assert isinstance(intent.field_path, FieldPath)
        assert isinstance(intent.source, IntentSource)
        assert intent.source.facet_id == SANDBOX_FACET_ID
        assert intent.source.contribution_version == SANDBOX_FACET_SCHEMA_VERSION
        assert intent.source.item_id == sandbox_item_id("codex")
        assert intent.kind == "set-field"
    mode = bound.intents[0]
    assert mode.field_path.segments == ("sandbox_mode",)
    assert mode.typed_value == "workspace-write"
    write = bound.intents[1]
    assert write.field_path.segments == ("sandbox_workspace_write",)
    # the structured value survives the platform's JSON sealing: a dict, and
    # no raw path write anywhere in it
    assert write.typed_value == {"writableRoots": ["src"], "networkAccess": False}


def test_claude_toggle_binds_a_real_setfield_and_claims_nothing_broader():
    compiled = _claude_fields()
    bound = compiled.to_harness_c3()
    assert isinstance(bound, IntentSet)
    assert all(isinstance(intent, SetField) for intent in bound.intents)
    assert {intent.field_path.segments for intent in bound.intents} == \
        {("bashSandbox",)}
    assert all(intent.typed_value is True for intent in bound.intents)


def test_pi_binds_the_action_form_of_the_c3_vocabulary():
    compiled = _pi_fields()
    bound = compiled.to_harness_c3()
    assert [type(intent) for intent in bound.intents] == [InvokeAction]
    action = bound.intents[0]
    assert action.action_id == "sandboxExtension"
    assert action.schema_version == SANDBOX_FACET_SCHEMA_VERSION
    assert action.typed_payload == "sandbox-ext"
    # an InvokeAction must declare what observation it expects — the platform
    # requires the field, this package does not invent a stand-in for it
    assert action.expected_observation == \
        "pi-sandbox-extension-loaded:sandbox-ext@2.0"


def test_reset_field_binds_with_a_platform_baseline_rule():
    compiled = _codex_fields().intents[0]
    reset = CompiledFieldIntent(
        field_path_segments=compiled.field_path_segments,
        value=None, kind="reset-field", intent=compiled.intent,
        target=compiled.target, baseline_rule="remove-key")
    bound = reset.to_harness_c3()
    assert isinstance(bound, ResetField)
    assert bound.baseline_rule == "remove-key"
    assert bound.field_path.segments == ("sandbox_mode",)


def test_the_kind_vocabulary_is_read_from_the_platform_classes():
    assert HARNESS_C3_INTENT_KINDS == {"set-field", "reset-field", "invoke-action"}
    for intent in _codex_fields().to_harness_c3().intents:
        assert intent.kind in HARNESS_C3_INTENT_KINDS


def test_an_unimplemented_kind_refuses_rather_than_inventing_an_intent():
    field = _codex_fields().intents[0]
    weird = CompiledFieldIntent(
        field_path_segments=("sandbox_mode",), value="read-only",
        kind="set-field", intent=field.intent, target=field.target)
    assert isinstance(weird.to_harness_c3(), SetField)
    # only the three sealed kinds exist at all; anything else cannot even be
    # constructed, let alone quietly mapped to something new
    with pytest.raises(ValueError):
        CompiledFieldIntent(field_path_segments=("sandbox_mode",), value="x",
                            kind="write-file", intent=field.intent,
                            target=field.target)


# ------------------------------------------------- no second vocabulary left
def test_the_package_keeps_no_parallel_apply_or_verdict_types():
    import ordessa_sandbox_adapters as pkg
    for gone in ("SandboxNativeConfigurationAdapter", "HarnessContractUnavailable",
                 "REQUIRED_HARNESS_API_CHECKPOINT", "AssessReport",
                 "AssessOutcome", "VerifyResult", "VerifyOutcome"):
        assert not hasattr(pkg, gone), gone


def test_compile_output_carries_the_platform_handle_it_was_bound_to():
    handle = target_handle(CODEX_TARGET, generation=4)
    compiled = CodexSandboxAdapter().compile(codex_intent(), handle,
                                             (permissive_ceiling(),))
    for field in compiled.intents:
        assert field.target is handle
        assert field.to_harness_c3().target.generation == 4
    # and a bare string target is refused: no handle is minted from a path/name
    refusal = CodexSandboxAdapter().compile(codex_intent(), "codex-config-toml",
                                            (permissive_ceiling(),))
    assert refusal.outcome == "refusal"
    assert refusal.code.value == "SANDBOX_INTENT_INVALID"


def test_a_refusal_never_produces_a_bound_intent_set():
    from ordessa_sandbox_adapters import CompileRefusal
    adapter = CodexSandboxAdapter()
    from _sandbox_adapters_helpers import codex_config
    refusal = adapter.compile(codex_intent(config=codex_config(
        sandbox_mode="danger-full-access")), target_handle(CODEX_TARGET),
        (permissive_ceiling(),))
    assert isinstance(refusal, CompileRefusal)
    assert refusal.intents == ()
    assert not hasattr(refusal, "to_harness_c3")


def test_verification_types_are_the_platforms_and_a_drift_is_never_confirmed():
    """Mismatch / VerificationUnknown are the only negative answers available:
    there is no local "verified" enum left that a caller could inflate into a
    confirmation — only the C4 service can answer ``Confirmed``, and only from
    its own verified native readback."""
    from _sandbox_adapters_helpers import effect_observation
    assert isinstance(_codex_fields().to_harness_c3(), IntentSet)
    outcomes = [CodexSandboxAdapter().verify(effect_observation(kind))
                for kind in ("verified", "unknown", "unsupported")]
    assert all(isinstance(v, (Match, Mismatch, VerificationUnknown))
               for v in outcomes)
    # a missing or negative probe is never reported as a match
    assert not any(isinstance(v, Match) for v in outcomes[1:])
    assert type(outcomes[1]) is VerificationUnknown
    assert type(outcomes[2]) is VerificationUnknown


def test_no_src_module_redefines_the_platform_vocabulary():
    """A guard against the second vocabulary the checkpoint makes unnecessary:
    nothing under ``src/`` may declare a class named like a platform contract
    type, nor import the harness CODE."""
    import ast
    src = Path(__file__).resolve().parents[1] / "src" / "ordessa_sandbox_adapters"
    names = BOUND_C3_SYMBOLS | BOUND_CONTRACT_SYMBOLS
    for path in sorted(src.glob("**/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert node.name not in names, \
                    f"{path.name} redefines the platform type {node.name!r}"
            if isinstance(node, ast.Import):
                roots = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = {node.module.split(".")[0]}
            else:
                continue
            assert "ordessa_harness" not in roots, \
                f"{path.name} imports harness CODE: {sorted(roots)}"
        for imported in _harness_api_imports(path):
            assert imported.split(".")[0] == "ordessa_harness_api", imported
            symbol = imported.split(".")[-1]
            assert symbol in names or symbol in {"looks_secret_name", "validate_json",
                                                 "closed_object", "JsonValue",
                                                 "ContractError", "ErrorCode",
                                                 "Installation", "ValueSchema",
                                                 "DesiredFragment", "Plan",
                                                 "PlanResult", "ApplicationTarget",
                                                 "ApplicationResult", "Confirmed",
                                                 "Refused", "Unknown",
                                                 "OperationRecord",
                                                 "ConfigurationCapabilities",
                                                 "ConfigurationService"}, imported


def _harness_api_imports(path: Path) -> set[str]:
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names
                      if a.name.startswith("ordessa_harness_api")}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module \
                and node.module.startswith("ordessa_harness_api"):
            found |= {f"{node.module}.{a.name}" for a in node.names}
    return found
