"""Original stable Server identity on the injected original DatabasePort.

No data-root choice, database creation, token, grant or Unit runtime is owned here.
The trusted host must hold its original database/root lifetime before calling.
"""
from datetime import datetime, timezone
from uuid import uuid4
from ordessa_interfaces.system_access.contracts.storage import DatabasePort


def _server_id(database: DatabasePort) -> str:
    """Return the stable, opaque identity this Server presents to clients.

    It is generated once per data root and reused across restarts, so a client
    can tell "the same Server came back" from "a different Server is here".
    """
    with database.transaction() as conn:
        row = conn.execute("SELECT server_id FROM server_bootstrap WHERE singleton=1").fetchone()
        if row is not None:
            return str(row["server_id"])
        identity = f"server_{uuid4().hex}"
        conn.execute(
            "INSERT INTO server_bootstrap(singleton,server_id,created_at) VALUES (1,?,?)",
            (identity, datetime.now(timezone.utc).isoformat()),
        )
        return identity
