"""Ordessa memory domain: the mem0 self-hosted leaf plugin (015 P-B).

Public surface (import-stable for consumers):

* :class:`MemoryPlugin` — the server plugin (wire family ``memory.*``,
  provided port ``assets.memory.service``, C2 + error-family contributions);
* :mod:`ordessa_memory.facet` — the ``assets.memory`` facet definition and
  the registration manifests the Profile side consumes;
* :mod:`ordessa_memory.bridge` — the real C2 ``ConfigurationAdapter``s;
* :mod:`ordessa_memory.common` — the shared vocabulary, the attribution
  line, and the byte-stable injection-block renderer.

The domain imports no other plugin's modules and no host internals.
"""
from .plugin import MemoryPlugin, MemoryService, PLUGIN_ID, REQUIRES

__all__ = ["MemoryPlugin", "MemoryService", "PLUGIN_ID", "REQUIRES"]
