"""T04b — NativeSandboxRepository: id+revision intents, instance-bound evidence.

The store is this domain's own (a Profile may only reference id+revision);
it is separate from any permissions data and survives facet uninstallation.
"""
from __future__ import annotations

import dataclasses

import pytest
from _sandbox_backend_helpers import claude_evidence, claude_intent, codex_intent, platform_facts, target_facts

from ordessa_sandbox_api import SandboxApiError, SandboxErrorCode
from ordessa_sandbox_backend import (
    NativeSandboxRepository,
    SandboxIntentReference,
    TargetFacts,
)


def test_intent_saved_and_queried_by_id_and_revision():
    repo = NativeSandboxRepository()
    repo.save_intent(claude_intent(revision=1))
    repo.save_intent(claude_intent(revision=2, write_scope=("docs",)))
    assert repo.get_intent("sbx-claude-1", 1).revision == 1
    assert repo.get_intent("sbx-claude-1", 2).write_scope == ("docs",)
    assert repo.latest("sbx-claude-1").revision == 2
    assert repo.get_intent("sbx-claude-1", 3) is None
    assert repo.get_intent("sbx-missing", 1) is None


def test_saving_a_stale_revision_is_refused_not_merged():
    repo = NativeSandboxRepository()
    repo.save_intent(claude_intent(revision=2))
    with pytest.raises(SandboxApiError) as exc:
        repo.save_intent(claude_intent(revision=1))
    assert exc.value.code is SandboxErrorCode.SANDBOX_INTENT_INVALID


def test_profile_reference_carries_only_id_and_revision():
    repo = NativeSandboxRepository()
    repo.save_intent(codex_intent())
    ref = repo.reference("sbx-codex-1", 1)
    assert isinstance(ref, SandboxIntentReference)
    names = {f.name for f in dataclasses.fields(ref)}
    assert names == {"sandbox_id", "revision"}
    # the reference resolves to the stored record, but carries no config itself
    assert not any(hasattr(ref, attr) for attr in ("config", "brand", "harness_id"))
    assert repo.resolve(ref).sandbox_id == "sbx-codex-1"


def test_evidence_is_keyed_by_target_handle_and_runtime_generation():
    repo = NativeSandboxRepository()
    repo.record_evidence("th-1", claude_evidence(runtime_generation="gen-1"))
    found = repo.get_evidence("th-1", "gen-1")
    assert found is not None and found.runtime_generation == "gen-1"
    assert repo.get_evidence("th-1", "gen-2") is None
    assert repo.get_evidence("th-other", "gen-1") is None


def test_native_version_change_invalidates_stored_verified_evidence():
    repo = NativeSandboxRepository()
    repo.record_evidence("th-1", claude_evidence())
    repo.update_facts("th-1", target_facts(native_version="0.81.3"))
    # a query after invalidation must not return the stale `verified` record
    assert repo.get_evidence("th-1", "gen-1") is None


def test_config_digest_change_invalidates():
    repo = NativeSandboxRepository()
    repo.record_evidence("th-1", claude_evidence())
    repo.update_facts("th-1", target_facts(config_digest="sha256:changed"))
    assert repo.get_evidence("th-1", "gen-1") is None


def test_platform_fact_change_invalidates():
    repo = NativeSandboxRepository()
    repo.record_evidence("th-1", claude_evidence())
    repo.update_facts("th-1", target_facts(
        platform=platform_facts(os_name="macos", os_version="15.1", kernel_features=())))
    assert repo.get_evidence("th-1", "gen-1") is None


def test_unchanged_facts_do_not_invalidate():
    repo = NativeSandboxRepository()
    repo.record_evidence("th-1", claude_evidence())
    repo.update_facts("th-1", target_facts())
    assert repo.get_evidence("th-1", "gen-1") is not None


def test_recording_evidence_bound_to_other_facts_is_refused_at_record_time():
    repo = NativeSandboxRepository()
    repo.update_facts("th-1", target_facts(native_version="0.81.3"))
    with pytest.raises(SandboxApiError) as exc:
        repo.record_evidence("th-1", claude_evidence(native_version="0.81.2"))
    assert exc.value.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_explicit_invalidation_returns_count_and_keeps_intents():
    repo = NativeSandboxRepository()
    repo.save_intent(claude_intent())
    repo.record_evidence("th-1", claude_evidence())
    assert repo.invalidate("th-1", reason="adapter reloaded") == 1
    assert repo.get_evidence("th-1", "gen-1") is None
    assert repo.get_intent("sbx-claude-1", 1) is not None  # intents are separate


def test_records_survive_uninstall_and_are_still_readable(tmp_path):
    # FR-08 persistence half: uninstalling the UI facet must not delete data.
    store_path = tmp_path / "sandbox-records.json"
    repo = NativeSandboxRepository.from_json_file(store_path)
    repo.save_intent(claude_intent(revision=1))
    repo.record_evidence("th-1", claude_evidence())
    reopened = NativeSandboxRepository.from_json_file(store_path)
    assert reopened.get_intent("sbx-claude-1", 1) is not None
