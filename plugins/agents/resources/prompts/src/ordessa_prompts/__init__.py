"""Ordessa Prompts domain (dist `ordessa-prompts`, plugin id
`ordessa.assets.prompts`).

Public entry points:

* `ordessa_prompts.api` — pure DTOs, content rules and the typed error
  family (importable with zero runtime effects);
* `ordessa_prompts.backend` — storage, records, service, import/export;
* `ordessa_prompts.plugin` — the Server plugin surface (`prompts.*`).
"""
from __future__ import annotations

__all__ = ["__version__"]
__version__ = "2.0.0a1"
