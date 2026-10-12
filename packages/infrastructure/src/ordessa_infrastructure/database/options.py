"""Explicit, business-neutral SQLite connection parameters.

The point of this module is to make the *effective* connection contract a
value: every caller that used to hand-write ``sqlite3.connect(...)`` plus a
handful of ``PRAGMA`` statements can instead build one :class:`SQLiteOptions`
and let :func:`ordessa_infrastructure.database.sqlite.create_connection` apply
it. Nothing here owns a schema, a migration, a transaction unit of work or a
store authority.

Design rules (they mirror the task's parameter contract):

* The returned object is a native :class:`sqlite3.Connection`; this module adds
  no wrapper and no connection registry.
* Parameters that Python would default are only passed to ``sqlite3.connect``
  when the caller set them (see :data:`UNSET`). Python 3.12's ``autocommit`` /
  ``isolation_level`` therefore cannot change silently just because a caller
  omitted them: an unset field reproduces plain ``sqlite3.connect`` behaviour.
* ``foreign_keys`` and ``busy_timeout`` are explicit opt-ins. ``None`` means
  "do not touch the connection default"; a value means "apply exactly this".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class _Unset:
    """Sentinel distinguishing "caller did not set this" from ``None``."""

    _instance: "_Unset | None" = None

    def __new__(cls) -> "_Unset":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "UNSET"

    def __bool__(self) -> bool:
        return False


#: Marker for "leave this ``sqlite3.connect`` parameter at its Python default".
UNSET = _Unset()


def _is_unset(value: Any) -> bool:
    return value is UNSET


@dataclass(frozen=True)
class SQLiteOptions:
    """One caller's explicit connection contract.

    Attributes
    ----------
    location:
        Database file path (or URI when ``uri=True``). Kept as given; callers
        own directory creation so a bare connection helper never creates a
        data root as a side effect.
    uri:
        Forwarded to ``sqlite3.connect``. Default ``False`` keeps the
        historical path-string behaviour.
    timeout:
        Forwarded to ``sqlite3.connect`` as its busy-handler duration. Note
        that ``sqlite3.connect`` also installs ``PRAGMA busy_timeout`` from
        this value; an explicit :attr:`busy_timeout` is applied afterwards and
        therefore wins (see the module README).
    check_same_thread:
        Forwarded to ``sqlite3.connect``. Default ``True`` is the native
        default.
    isolation_level:
        Forwarded only when set. ``None`` selects SQLite autocommit
        (implicit-BEGIN disabled); ``""`` (the native default) keeps implicit
        transactions. Leaving this :data:`UNSET` reproduces the native default.
    autocommit:
        Forwarded only when set (Python 3.12). Leaving this :data:`UNSET`
        reproduces ``sqlite3.LEGACY_TRANSACTION_CONTROL``. When not legacy,
        Python ignores ``isolation_level``; both explicitly supplied values
        are forwarded without introducing another transaction policy.
    row_factory:
        Applied after connect when not ``None``. ``None`` means "leave the
        native tuple factory".
    foreign_keys:
        ``True``/``False`` executes exactly that ``PRAGMA foreign_keys``.
        ``None`` leaves the connection's foreign-key setting untouched.
    busy_timeout:
        Milliseconds applied via ``PRAGMA busy_timeout`` when not ``None``.
        Overrides the value ``sqlite3.connect`` derived from ``timeout``.
    """

    location: str | Path
    uri: bool = False
    timeout: float = 5.0
    check_same_thread: bool = True
    isolation_level: Any = field(default=UNSET)
    autocommit: Any = field(default=UNSET)
    row_factory: Callable[..., Any] | None = None
    foreign_keys: bool | None = None
    busy_timeout: int | None = None

    def connect_kwargs(self) -> dict[str, Any]:
        """The ``sqlite3.connect`` keyword arguments implied by this contract.

        Only explicitly set transaction-control parameters are included, so an
        omitted ``isolation_level``/``autocommit`` cannot alter Python 3.12
        behaviour relative to a plain ``sqlite3.connect`` call.
        """
        kwargs: dict[str, Any] = {
            "timeout": self.timeout,
            "uri": self.uri,
            "check_same_thread": self.check_same_thread,
        }
        if not _is_unset(self.isolation_level):
            kwargs["isolation_level"] = self.isolation_level
        if not _is_unset(self.autocommit):
            kwargs["autocommit"] = self.autocommit
        return kwargs
