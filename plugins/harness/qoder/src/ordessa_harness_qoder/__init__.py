"""Third-party Qoder CLI family (Work Order 114).

Order 114 wires Qoder as the independent ninth family. This package currently
holds the **native-config key registry** (item #6 / G5): the honest, first-hand
record of which ``~/.qoder`` keys this order understands and which it read but
could not interpret (registered, never invented, never dropped).

The production deployment template (packaging/mount, item #1), the account-login
path (item #3, which consumes the 094/095 account model), cross-platform
placement (item #4) and the live chain gate (item #5) land in later 114 stages;
they are intentionally absent here rather than half-wired - the family is not
registered as executable until its login + artifact legs exist, so no layer can
mistake a catalog entry for a working Harness.
"""
from .native_config import (
    CLASSIFICATION_UNKNOWN,
    NativeKey,
    QODER_CLI_ROOT,
    QODER_NATIVE_HOME,
    QODER_NATIVE_KEYS,
    QODER_SEC_ROOT,
    registered_keys,
    unregistered_keys,
)

__all__ = [
    "CLASSIFICATION_UNKNOWN", "NativeKey", "QODER_CLI_ROOT", "QODER_NATIVE_HOME",
    "QODER_NATIVE_KEYS", "QODER_SEC_ROOT", "registered_keys", "unregistered_keys",
]
