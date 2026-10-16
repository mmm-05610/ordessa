"""Pinned claude-code runtime construction over an explicit host factory."""
from ordessa_execution_agents.harness.definitions import Installation
NATIVE_VERSION = (0, 81, 2)


def ClaudeLiveModelRuntime(registry, owners, *, target, installation, private_root,
                       publication_revision, runtime_factory, context_factory,
                       credential_binding=None):
    if not callable(runtime_factory) or not callable(context_factory):
        raise ValueError("Explicit live runtime and context factories required")
    if (not isinstance(installation, Installation) or installation.harness_id != 'claude-code'
            or installation.native_version != NATIVE_VERSION
            or not isinstance(publication_revision, str) or not publication_revision):
        raise ValueError("Verified pinned native installation and publication required")
    return runtime_factory(registry, owners, target=target, installation=installation,
        private_root=private_root, publication_revision=publication_revision,
        credential_binding=credential_binding, harness_id='claude-code',
        native_version=NATIVE_VERSION, context_factory=context_factory)


ClaudeLiveModelRuntime.native_version = NATIVE_VERSION


def declared_runtime_version():
    return NATIVE_VERSION
