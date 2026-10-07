"""sandbox.describe@1 shape: options only from the matrix, never guessed."""
from __future__ import annotations

import pytest
from _sandbox_api_helpers import codex_intent

from ordessa_sandbox_api import (
    CellStatus,
    SandboxApiError,
    SandboxCeiling,
    SandboxDescription,
    SandboxErrorCode,
    describe_sandbox,
)


def test_describe_codex_lists_pinned_mode_options():
    description = describe_sandbox(
        harness_id="codex", native_version="0.147.0",
        platform_os="linux", platform_version="6.6",
    )
    ids = {option.option_id for option in description.options}
    assert "sandbox_mode=read-only" in ids
    assert "sandbox_mode=workspace-write" in ids


def test_describe_records_source_and_status_per_option():
    description = describe_sandbox(
        harness_id="codex", native_version="0.147.0",
        platform_os="linux", platform_version="6.6",
    )
    for option in description.options:
        assert option.source, "every option states where it comes from"
        assert isinstance(option.status, CellStatus)


def test_options_for_ui_hides_unknown_and_unsupported():
    description = describe_sandbox(
        harness_id="claude-code", native_version="2.1.270",
        platform_os="linux", platform_version="6.6",
    )
    assert all(option.status is CellStatus.SUPPORTED
               for option in description.options_for_ui())


def test_selecting_unsupported_option_refuses():
    description = describe_sandbox(
        harness_id="claude-code", native_version="2.1.270",
        platform_os="windows", platform_version="11",
    )
    with pytest.raises(SandboxApiError) as excinfo:
        description.select("bash_sandbox=enabled")
    assert excinfo.value.code in (SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                                  SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED)


def test_selecting_unknown_option_refuses_rather_than_guessing():
    description = describe_sandbox(
        harness_id="claude-code", native_version="2.1.270",
        platform_os="linux", platform_version="6.6",
    )
    unknown = next(o for o in description.options if o.status is CellStatus.UNKNOWN)
    with pytest.raises(SandboxApiError) as excinfo:
        description.select(unknown.option_id)
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_brand_without_matrix_rows_gets_no_menu():
    # UI must not invent a menu from the brand name: an unbranded harness
    # describes as zero options, not as a copy of another brand's vocabulary.
    description = describe_sandbox(
        harness_id="totally-other", native_version="9.9",
        platform_os="linux", platform_version="6.6",
    )
    assert description.options == ()
    with pytest.raises(SandboxApiError) as excinfo:
        description.select("sandbox_mode=read-only")
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED


def test_admin_lock_is_surfaced():
    description = describe_sandbox(
        harness_id="codex", native_version="0.147.0",
        platform_os="linux", platform_version="6.6",
        admin_lock=SandboxCeiling(brand="codex", enforce=True, minimum_strictness=3),
    )
    assert description.locked_by_administrator is True
    mode = description.select("sandbox_mode=read-only")
    assert mode.locked_by_administrator is True


def test_no_admin_lock_by_default():
    description = describe_sandbox(
        harness_id="codex", native_version="0.147.0",
        platform_os="linux", platform_version="6.6",
    )
    assert description.locked_by_administrator is False


def test_busy_provider_refuses_with_provider_busy():
    with pytest.raises(SandboxApiError) as excinfo:
        describe_sandbox(
            harness_id="codex", native_version="0.147.0",
            platform_os="linux", platform_version="6.6",
            provider_state="busy",
        )
    assert excinfo.value.code is SandboxErrorCode.PROVIDER_BUSY


def test_unloaded_provider_refuses_with_provider_busy():
    with pytest.raises(SandboxApiError) as excinfo:
        describe_sandbox(
            harness_id="codex", native_version="0.147.0",
            platform_os="linux", platform_version="6.6",
            provider_state="unloaded",
        )
    assert excinfo.value.code is SandboxErrorCode.PROVIDER_BUSY


def test_description_carries_platform_assessment():
    description = describe_sandbox(
        harness_id="claude-code", native_version="2.1.270",
        platform_os="windows", platform_version="11",
    )
    assert description.platform_assessment is not None
    assert isinstance(description, SandboxDescription)
