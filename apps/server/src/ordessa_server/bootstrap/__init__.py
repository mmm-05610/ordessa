"""The generic host composition root. Business composition lives in the
product package (`products/server`) and the domain plugins; nothing here
imports either."""
from ordessa_server.bootstrap.runtime import (
    SERVER_PRODUCT_ENTRY_POINT,
    DataRootOwner,
    DataRootPathUnsafeError,
    EventNotifier,
    LegacyMigrationProviderMissingError,
    StorageProviderMissingError,
    ServerRuntime,
    _resolve_product_composition,
    build_runtime,
)

#: C-01's data-root surface. The layout literals live in ONE json file that
#: the TypeScript host reads as well; nothing here restates them.
from ordessa_server.bootstrap.data_root import (  # noqa: E402  (layout after runtime)
    BACKUPS_DIR,
    DATA_ROOT_ENV,
    DEFAULT_DATA_ROOT_DIRNAME,
    INSTANCE_LOCK,
    LAYOUT,
    LOGS_DIR,
    SECRETS_DIR,
    SERVER_LOG_FILE,
    TOKEN_FILE,
    DataRoot,
    DataRootError,
    DataRootInvalidError,
    DataRootLockedError,
    DataRootMigrationRefusedError,
    DataRootNotWritableError,
    DataRootSpec,
    DataRootSymlinkError,
    InstanceLock,
    ensure_data_root,
    instance_lock,
    launch_env,
    logs_dir,
    require_migration_provider_for_historical_root,
    resolve_data_root,
    server_log_file,
    token_file,
)

__all__ = [
    "SERVER_PRODUCT_ENTRY_POINT", "DataRootOwner", "EventNotifier",
    "ServerRuntime", "LegacyMigrationProviderMissingError",
    "DataRootPathUnsafeError", "StorageProviderMissingError", "build_runtime",
    "_resolve_product_composition",
    "BACKUPS_DIR", "DATA_ROOT_ENV", "DEFAULT_DATA_ROOT_DIRNAME",
    "INSTANCE_LOCK", "LAYOUT", "LOGS_DIR", "SECRETS_DIR", "SERVER_LOG_FILE",
    "TOKEN_FILE", "DataRoot", "DataRootError", "DataRootInvalidError",
    "DataRootLockedError", "DataRootMigrationRefusedError",
    "DataRootNotWritableError", "DataRootSpec", "DataRootSymlinkError",
    "InstanceLock", "ensure_data_root", "instance_lock", "launch_env",
    "logs_dir", "require_migration_provider_for_historical_root",
    "resolve_data_root", "server_log_file", "token_file",
]
