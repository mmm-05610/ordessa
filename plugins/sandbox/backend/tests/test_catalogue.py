"""T04b — SandboxOptionCatalogue: menus come from repo pins, never brand guesses."""
from __future__ import annotations

import pytest
from _sandbox_backend_helpers import repo_toml_text

from ordessa_sandbox_api import (
    BRAND_OPTIONS,
    CellStatus,
    SandboxCeiling,
    SandboxErrorCode,
)
from ordessa_sandbox_backend import (
    CatalogueStatus,
    SandboxOptionCatalogue,
)


@pytest.fixture()
def catalogue():
    # Built from the real repo harnesses.toml + the API brand matrix.
    from pathlib import Path
    from _sandbox_backend_helpers import HARNESSES_TOML
    return SandboxOptionCatalogue.from_repo(harnesses_toml=Path(HARNESSES_TOML))


def test_known_codex_pin_lists_pinned_modes_with_source_and_platforms(catalogue):
    result = catalogue.lookup("codex", "2.0", platform_os="linux")
    assert result.status is CatalogueStatus.AVAILABLE
    ids = {option.option_id for option in result.options}
    assert "sandbox_mode=workspace-write" in ids
    for option in result.options:
        assert option.source  # every option names its repo-measured origin
        assert option.platforms  # platform limits are carried, not guessed
    # the menu equals the API brand options for that pin (single source)
    assert ids == {proto.option_id for proto in BRAND_OPTIONS["codex"]}


def test_unknown_pin_returns_explicit_unknown_and_invents_no_menu(catalogue):
    result = catalogue.lookup("codex", "9.9.9", platform_os="linux")
    assert result.status is CatalogueStatus.UNKNOWN
    assert result.options == ()  # no menu is invented
    with pytest.raises(Exception) as exc:
        result.select("sandbox_mode=read-only")
    assert getattr(exc.value, "code", None) is SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED


@pytest.mark.parametrize("harness_id", ["opencode", "hermes", "dsh", "qwen", "kilo"])
def test_family_without_closed_schema_is_unknown(catalogue, harness_id):
    # harnesses.toml pins these families, but only codex/claude-code/pi have
    # measured native-sandbox vocabularies; the others never get a menu.
    result = catalogue.lookup(harness_id, "2.0", platform_os="linux")
    assert result.status is CatalogueStatus.UNKNOWN
    assert result.options == ()


def test_pi_pin_is_known_with_empty_menu(catalogue):
    # Pi is extension-backed: a known pin whose offered options are empty,
    # distinct from an unknown pin.
    result = catalogue.lookup("pi", "2.0", platform_os="linux")
    assert result.status is CatalogueStatus.AVAILABLE
    assert result.options == ()
    with pytest.raises(Exception) as exc:
        result.select("bash_sandbox=enabled")
    assert getattr(exc.value, "code", None) is SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED


def test_claude_pin_menu_carries_unproven_status_not_guessed_supported(catalogue):
    result = catalogue.lookup("claude-code", "0.81.2", platform_os="linux")
    assert result.status is CatalogueStatus.AVAILABLE
    bash = next(o for o in result.options if o.option_id == "bash_sandbox=enabled")
    assert bash.status is CellStatus.UNKNOWN  # documented only; not click-to-green
    # unknown options never reach the UI menu
    assert all(o.status is CellStatus.SUPPORTED for o in result.menu())


def test_admin_lock_marks_options_locked_by_administrator(catalogue):
    ceiling = SandboxCeiling(brand="codex", enforce=True, minimum_strictness=2)
    result = catalogue.lookup("codex", "2.0", platform_os="linux", admin_lock=ceiling)
    locked = {o.option_id for o in result.options if o.locked_by_administrator}
    assert "sandbox_mode=workspace-write" in locked
    assert result.locked_by_administrator is True


def test_catalogue_pin_matches_repo_harnesses_toml():
    # the catalogue reads real pins; drop the toml fixture and it must not
    # silently invent them
    from pathlib import Path
    from _sandbox_backend_helpers import HARNESSES_TOML
    text = repo_toml_text()
    assert 'harness_type = "codex"' in text and 'version = "0.81.2"' in text
    cat = SandboxOptionCatalogue.from_repo(harnesses_toml=Path(HARNESSES_TOML))
    assert cat.known_pin("claude-code", "0.81.2") is True
    assert cat.known_pin("claude-code", "0.0.1") is False
