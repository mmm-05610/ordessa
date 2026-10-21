"""Explicit native-resource import helpers.

**Unwired / not connected.** No live consumer imports this package (the
`ImportPreview` symbols in the subagents plugin are that plugin's own DTOs, not
these). The implementation is kept intact and is *not* replaced by an empty
directory; the import path remains unregistered until a real consumer is wired
explicitly.
"""
