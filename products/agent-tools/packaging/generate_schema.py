"""Build-time schema mirror; requires the source core public package only here."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check or explicitly regenerate the core-owned client schema")
    parser.add_argument("--write", action="store_true", help="Replace the client schema mirror from core authority")
    options = parser.parse_args(argv)
    # Never imported by runtime client code or included in its wheel package.
    from pacthold.agents.public import wire_contract, wire_schema_digest
    mirror = Path(__file__).resolve().parents[1] / "src/ordessa_agent_tools/schema.json"
    value = {"schema": wire_contract(), "schemaDigest": wire_schema_digest()}
    if options.write:
        mirror.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if json.loads(mirror.read_text(encoding="utf-8")) != value:
        raise SystemExit("Client schema mirror differs from the core public contract")
    print("Core schema mirror verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
