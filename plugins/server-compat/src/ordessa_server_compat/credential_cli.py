"""One-shot credential import; this command never launches a model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Import a Codex login into the Ordessa Server")
    value.add_argument("--data-root", type=Path, required=True)
    value.add_argument("--source", type=Path, required=True)
    value.add_argument(
        "--confirm-source", type=Path, required=True,
        help="repeat the exact authorized source path",
    )
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    source = args.source.resolve(strict=True)
    try:
        confirmed = args.confirm_source.resolve(strict=True)
    except OSError as exc:
        parser().error(f"--confirm-source is unavailable: {exc}")
    if source != confirmed:
        parser().error("--confirm-source must resolve to the exact --source path")

    from ordessa_server.bootstrap import build_runtime
    from pacthold.storage import WindowsDpapiSecretStore

    runtime = build_runtime(args.data_root)
    store = WindowsDpapiSecretStore(runtime.data_root)
    locator = None
    try:
        runtime.start()
        credential_id, locator = store.import_file(source, "codex-login")
        try:
            result = runtime.repository.register_credential(
                credential_id, "codex-login", locator,
            )
        except BaseException:
            store.delete(locator)
            raise
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        runtime.stop()


if __name__ == "__main__":
    raise SystemExit(main())
