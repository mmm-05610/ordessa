"""Deployment verifier for the managed Hermes runtime artifact (non-secret).

Why this file exists - measured, not assumed:

* Hermes keeps its authoritative native session store in SQLite at
  ``$HERMES_HOME/state.db`` (per ``hermes_state.DEFAULT_DB_PATH`` and
  ``acp_adapter.session.SessionManager._get_db``), with ``state.db-wal`` and
  ``state.db-shm`` beside it. The store is therefore a *file directly inside*
  the Hermes home, not a subdirectory of it.
* The AgentBox deployment persists exactly one writable directory per Harness
  home (``stateProjection.target``) and projects reviewed files read-only
  (``projectionFiles``) inside the one isolated guest home root
  (``/runtime/home``); Hermes 0.19 exposes no configuration key or environment
  variable that relocates ``state.db``.
* Consequently ``HERMES_HOME`` *is* the persisted directory, and the reviewed
  ``config.yaml`` is projected read-only *inside* it - at exactly the path
  Hermes itself reads (``$HERMES_HOME/config.yaml``). Nothing has to be copied
  into the home, and nothing may be: the reviewed file is a read-only mount, so
  a write attempt fails instead of silently forking a second configuration that
  the next turn would read.

This module therefore does not materialize anything. It *verifies* that the
reviewed configuration is really in place before Hermes reads it, then records
what it saw. Failures are loud, because a Hermes that starts without its
reviewed configuration would talk to the default endpoint instead of the
configured one - and would keep its sessions somewhere the deployment never
declared.

The file is copied into the artifact as ``agentbox_hermes_bootstrap.py``;
``sitecustomize.py`` (also part of the artifact) is what CPython imports at
interpreter start, and the reviewed offline gate calls :func:`apply` directly.
Both paths run this same code.
"""
from __future__ import annotations

import hashlib
import os

#: The errnos a refused write to a read-only mount or file reports: EROFS (the
#: read-only bind the deployment uses), EACCES/EPERM (a read-only file).
READ_ONLY_ERRNOS = frozenset({1, 13, 30})

#: The one isolated guest home root. The reviewed configuration is projected
#: inside it and never comes from the host, so a home outside this root is a
#: deployment this module refuses to verify (fail closed).
HOME_ROOT = "/runtime/home"
#: The environment variable the deployment declares, and the file Hermes reads.
HOME_ENVIRONMENT = "HERMES_HOME"
CONFIG_NAME = "config.yaml"
#: Audit sink, set by the offline gate only; unset in production.
AUDIT_ENVIRONMENT = "AGENTBOX_BOOTSTRAP_AUDIT"


class HermesBootstrapError(RuntimeError):
    """A deployment this verifier refuses to start inside."""


def _record(line: str) -> None:
    location = os.environ.get(AUDIT_ENVIRONMENT)
    if not location:
        return
    try:
        with open(location, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        # Auditing must never be the reason the deployment fails to start.
        pass


def home() -> str:
    """The Hermes home this deployment declares, refused when it is unusable."""
    value = (os.environ.get(HOME_ENVIRONMENT) or "").strip()
    if not value:
        raise HermesBootstrapError("AGENTBOX_HERMES_BOOTSTRAP_HOME_MISSING")
    if not value.startswith("/"):
        raise HermesBootstrapError("AGENTBOX_HERMES_BOOTSTRAP_HOME_NOT_ABSOLUTE")
    if os.path.normpath(value) != value:
        raise HermesBootstrapError("AGENTBOX_HERMES_BOOTSTRAP_HOME_NOT_CANONICAL")
    if value != HOME_ROOT and not value.startswith(HOME_ROOT + "/"):
        # A home outside the isolated root would be a host directory.
        raise HermesBootstrapError("AGENTBOX_HERMES_BOOTSTRAP_HOME_OUTSIDE_ISOLATION")
    return value


def config_path(target_home: str) -> str:
    """The reviewed configuration's path inside that home."""
    return os.path.join(target_home, CONFIG_NAME)


def apply() -> dict[str, object]:
    """Verify the reviewed configuration is the file Hermes will read.

    The check is deliberately about the *bytes that are really there*: the
    projected file must exist, be a regular file (never a symlink, which would
    mean the run resolved a path the deployment never declared), be non-empty,
    and be **read-only**. Its digest is recorded so a gate can compare what
    Hermes read with what the deployment projected.

    The read-only probe is what makes "the configuration cannot change during
    the run" an observation: a writable reviewed file would let anything that
    can write the state directory also rewrite the endpoint, model or
    credential reference of the next turn.
    """
    target_home = home()
    path = config_path(target_home)
    if os.path.islink(path) or not os.path.isfile(path):
        raise HermesBootstrapError("AGENTBOX_HERMES_BOOTSTRAP_CONFIG_MISSING")
    try:
        with open(path, "rb") as handle:
            content = handle.read()
    except OSError as error:
        raise HermesBootstrapError(
            f"AGENTBOX_HERMES_BOOTSTRAP_CONFIG_UNREADABLE: {type(error).__name__}",
        ) from error
    if not content:
        raise HermesBootstrapError("AGENTBOX_HERMES_BOOTSTRAP_CONFIG_EMPTY")
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    posture = _readonly_posture(path)
    _record(
        f"bootstrap-verified home={target_home} config={path} "
        f"digest={digest} bytes={len(content)} {posture}",
    )
    return {
        "home": target_home, "config": "verified", "path": path,
        "digest": digest, "bytes": len(content), "posture": posture,
    }


def _readonly_posture(path: str) -> str:
    """Refuse a reviewed configuration that is not a read-only mount."""
    try:
        handle = open(path, "a", encoding="utf-8")  # noqa: SIM115 - closed immediately
    except OSError as error:
        if error.errno in READ_ONLY_ERRNOS:
            return f"posture=read-only code={error.errno}"
        raise HermesBootstrapError(
            f"AGENTBOX_HERMES_BOOTSTRAP_CONFIG_POSTURE_UNEXPECTED: {type(error).__name__}",
        ) from error
    handle.close()
    raise HermesBootstrapError("AGENTBOX_HERMES_BOOTSTRAP_CONFIG_WRITABLE")


if __name__ == "__main__":  # pragma: no cover - operator convenience
    print(apply())
