"""Agent-Box runtime compatibility assembly layered on the Pacthold kernel.

specs/010 platform-core T009 (FR-011): this distribution owns the business
SDK surface relocated out of the kernel — resource contracts, capability
documents, profile envelopes, runtime composition, the sandbox port shim,
the product persistence schema, the sealed historical migration chain and
the Web launcher CLI.  Import direction is one way: this package imports
``pacthold``; no kernel file imports or re-exports this package.
"""
from __future__ import annotations

__version__ = "0.1.0"
