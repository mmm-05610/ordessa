"""Work Order 114 item #6 / G5: the Qoder native-config key registry is honest.

Two properties the ticket demands, each one a gate:

* **register, don't invent** - every entry that is not understood carries no
  meaning and a first-hand source; no entry hands back a hallucinated
  interpretation;
* **register, don't drop** - a key the registry has never accounted for is
  *reported* by :func:`unregistered_keys`, not silently ignored.

The credential/privacy discipline is asserted too: the login state under
``.auth/`` is never a config key this materializer reaches for.
"""
from __future__ import annotations

from ordessa_harness_qoder import native_config


def _documents():
    return {
        "settings.json",
        native_config.QODER_SEC_ROOT,
        native_config.QODER_CLI_ROOT,
    }


def test_every_registered_key_cites_a_first_hand_source():
    """G5 "逐条给出处": no entry lands without where it was observed."""
    assert native_config.QODER_NATIVE_KEYS, "the registry must not be empty"
    for entry in native_config.QODER_NATIVE_KEYS:
        assert entry.source.strip(), f"{entry.key} has no source"
        assert entry.classification in {"known", "app_local", native_config.CLASSIFICATION_UNKNOWN}
        assert entry.document in _documents() | {"state.json"}, entry.document


def test_unknown_keys_carry_no_invented_meaning():
    """A key this order cannot interpret must have meaning == None (不发明语义)."""
    for entry in native_config.QODER_NATIVE_KEYS:
        if entry.classification == native_config.CLASSIFICATION_UNKNOWN:
            assert entry.meaning is None, f"{entry.key} invented a meaning"
        elif entry.classification == "known":
            assert entry.meaning, f"{entry.key} is known but says nothing"


def test_a_key_the_registry_never_saw_is_reported_not_dropped():
    """The silent-drop gate: an unaccounted Qoder key surfaces for registration."""
    settings = {
        "permissions": {"trustDirectories": ["/home/user/proj"]},  # registered
        "model": {"name": "qoder-pro"},                            # registered
        "brandNewQoderField": {"nested": 1},                        # NEVER registered
    }
    unknown = native_config.unregistered_keys(settings, document_name="settings.json")
    assert "brandNewQoderField.nested" in unknown
    # Registered leaves are not reported as unknown.
    assert "permissions.trustDirectories" not in unknown
    assert "model.name" not in unknown


def test_registering_the_novel_key_clears_it():
    """The counter-example: add the key to the registry and it stops being unknown.

    This proves the gate is reading the registry, not hard-coding a pass - if the
    drop were silent this assertion could not flip.
    """
    extra = native_config.NativeKey(
        "brandNewQoderField.nested", "settings.json", "known",
        "test-only registration", "unit test",
    )
    original = native_config.QODER_NATIVE_KEYS
    object.__setattr__(native_config, "QODER_NATIVE_KEYS", (*original, extra))
    try:
        settings = {"brandNewQoderField": {"nested": 1}}
        assert native_config.unregistered_keys(
            settings, document_name="settings.json") == []
    finally:
        object.__setattr__(native_config, "QODER_NATIVE_KEYS", original)


def test_the_login_state_is_not_a_config_key():
    """`.auth/` is account state (094/095's model), never config materialized here."""
    for entry in native_config.QODER_NATIVE_KEYS:
        assert not entry.key.startswith(".auth"), (
            f"{entry.key} reaches login state from the config materializer")
        assert entry.document != ".auth"
    # The roots this order declares are exactly the three first-hand ones.
    assert native_config.QODER_NATIVE_HOME == ".qoder"
    assert native_config.QODER_SEC_ROOT == ".qodersec"
    assert native_config.QODER_CLI_ROOT == ".qoder-cli"


def test_no_credential_value_is_stored_in_the_registry():
    """Privacy/credential discipline: keys + classifications only, never secret values."""
    import json
    blob = json.dumps([entry.__dict__ for entry in native_config.QODER_NATIVE_KEYS])
    for marker in ("sk-", "Bearer ", "machine_id", "installation_id"):
        assert marker not in blob, f"{marker} looks like credential/device material in the registry"
