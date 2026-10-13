"""CPython startup hook for the managed Hermes runtime artifact.

CPython imports a top-level ``sitecustomize`` module at interpreter start when
it is importable from ``sys.path``. The deployment runs the adapter with
``PYTHONPATH=<artifact>/site-packages``, so this module is that hook: it runs the
reviewed AgentBox Hermes verifier (:mod:`agentbox_hermes_bootstrap`) before
Hermes reads any configuration.

All behavior lives in the verifier module - this file only calls it, so the
reviewed offline gate, which puts its own ``sitecustomize`` earlier on
``sys.path``, runs exactly the same code path.

A failure here is fatal on purpose. CPython swallows ordinary exceptions raised
by ``sitecustomize`` (it prints them and keeps starting), and a managed Hermes
that starts without its reviewed configuration would silently use the tool's
default endpoint, model and session store. ``SystemExit`` is not an ``Exception``
and is not swallowed, so the adapter process dies with the reason on stderr
instead.
"""
from __future__ import annotations

import agentbox_hermes_bootstrap


def _start() -> None:
    try:
        agentbox_hermes_bootstrap.apply()
    except BaseException as error:  # noqa: BLE001 - re-raised as a fatal exit
        raise SystemExit(f"AGENTBOX_HERMES_CONFIG_UNVERIFIED: {error}") from error


_start()
