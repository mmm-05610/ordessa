"""Ordessa command-templates domain (``ordessa_command_templates``).

A standalone domain distribution holding reusable *one-shot parameterised user
messages*, their immutable revisions, their enable/disable assignments and a
closed, deterministic expansion engine. It executes no code, contributes no
persistent system/developer prompt layer, and is not a Skill repository
(``docs/design/command-templates/README.md``).

Import discipline (gate G01/G20, ``tests/test_isolation.py``):

* importing this package — or any module below it — opens no database, touches
  no filesystem, spawns nothing and registers no wire method. Every store and
  service is constructed explicitly with an injected private data-root path or
  an injected connection;
* the pure domain (``api``, ``library``, ``expansion``, ``assignments``) has
  **no** import of ``ordessa_server``, ``pacthold``, ``ordessa_harness``,
  ``ordessa_profile`` or any Chat/Workbench host module. Dependency direction is
  one way: the product composes this domain, never the reverse;
* the optional Server seam (``plugin``) is the only module that may import
  ``server_plugin_api`` descriptors, and only to describe methods when a host
  calls ``build()`` — importing the module still registers nothing.
"""
from __future__ import annotations

from .api.errors import (
    CapabilityUnknownError,
    CasConflictError,
    CommandTemplateError,
    ContributorGoneError,
    ContentMissingError,
    IdempotencyConflictError,
    InvalidDocumentError,
    InvalidIdentifierError,
    NameConflictError,
    NativeUnsupportedError,
    OutputLimitError,
    ParameterInvalidError,
    ProjectionRefusedError,
    RevisionUnapprovedError,
    StalePreviewError,
    UnauthorizedTargetError,
    UnknownParameterError,
    UnresolvedParameterError,
)

__all__ = [
    "CommandTemplateError",
    "InvalidIdentifierError",
    "InvalidDocumentError",
    "UnauthorizedTargetError",
    "ContentMissingError",
    "RevisionUnapprovedError",
    "ParameterInvalidError",
    "UnknownParameterError",
    "UnresolvedParameterError",
    "OutputLimitError",
    "NameConflictError",
    "StalePreviewError",
    "CasConflictError",
    "IdempotencyConflictError",
    "ContributorGoneError",
    "NativeUnsupportedError",
    "CapabilityUnknownError",
    "ProjectionRefusedError",
]
