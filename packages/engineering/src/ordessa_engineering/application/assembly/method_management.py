"""Compose the original authorized method selection/control owner."""
from ..usecases.support.methods import MethodUseCases


def build_method_management(factory, *, access, snapshots, management):
    """Return original adopt/control commands; inject actual management admission.

    Factory and snapshots must share the original library. Access and the
    through-COMMIT management guard are checked by the original commands;
    absent authority refuses. No permission, selection or alternate journal
    is created by composition.
    """
    return MethodUseCases(factory, access, snapshots, management)


__all__ = ['build_method_management']
