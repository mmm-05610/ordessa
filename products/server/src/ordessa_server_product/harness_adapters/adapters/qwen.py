from .generic_cli import GenericCliAdapter


class QwenAdapter(GenericCliAdapter):
    """qwen's local CLI composition shape.

    The managed production chain composes the pinned artifact's `qwen --acp`
    entry through the generic ACP registration; this adapter only names the
    driver in the local CLI composition seam.
    """
