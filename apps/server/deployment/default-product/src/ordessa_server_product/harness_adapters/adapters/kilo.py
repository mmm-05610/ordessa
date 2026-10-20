from .generic_cli import GenericCliAdapter


class KiloAdapter(GenericCliAdapter):
    """kilo's local CLI composition shape.

    The managed production chain composes the pinned artifact's native binary
    (`kilo acp`) through the generic ACP registration; this adapter only names
    the driver in the local CLI composition seam.
    """
