from .generic_cli import GenericCliAdapter


class DshAdapter(GenericCliAdapter):
    """dsh's local CLI composition shape.

    The managed production chain does not pass through here: it composes the
    pinned artifact's `dsh --profile acp` entry through the generic ACP
    registration. This adapter only gives the driver a name in the local CLI
    composition seam, with dsh's registry-declared launch argv.
    """
