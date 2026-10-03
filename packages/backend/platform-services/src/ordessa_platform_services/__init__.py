"""``ordessa_platform_services`` — optional E4 platform adapters.

No Environment, no plugin-activation registry, no business schema: only
file data areas and secret-reference accounting. The SQLite store lives in
its own package (``ordessa-persistence-sqlite``) behind the same frozen
ports (platform-services.md §公开实现落点).
"""
from .data_area import DataAreaError, FileDataAreaAdapter
from .secrets import SecretRefAdapter

__all__ = ["DataAreaError", "FileDataAreaAdapter", "SecretRefAdapter"]
