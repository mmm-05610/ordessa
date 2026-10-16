"""Independent native model provider declarations for explicit host capture."""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class NativeModelProviderPort:
    harness_id: str
    native_version: tuple
    descriptor: Callable
    initial_params: Callable
    create_runtime: Callable
    verify_installation: Callable
    create_action_executor: Callable
    requires_catalog: Callable
    prepare: Callable
    launch: Callable
    create_managed_account: Callable
    authenticated: Callable
    managed_account_supported: bool
    publication_unavailable_message: str
    live_registration: bool
    provider_restoration: bool
    single_root_alias: bool = False
