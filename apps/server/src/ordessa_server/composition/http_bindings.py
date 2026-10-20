"""Explicit existing HTTP identity and context mapping; no authority issuance."""
from dataclasses import dataclass
from typing import Callable
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority


@dataclass(frozen=True)
class HttpOwnerBindings:
    authority: InstanceAccessAuthority
    context_factory: Callable
    server_id: str

    def __post_init__(self):
        if type(self.authority) is not InstanceAccessAuthority or not callable(self.context_factory):
            raise TypeError('original instance authority and trusted context mapping required')
        if type(self.server_id) is not str or not self.server_id or len(self.server_id)>512:
            raise ValueError('original bounded Server identity required')
