"""Verify current owner data schemas; never regenerate retired runtime mirrors.

The old client /1-/3/provider schema assets are historical and do not qualify a
current client bundle. Client operation migration is a separate acceptance gate.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write',action='store_true')
    options=parser.parse_args(argv)
    from ordessa_execution_agents.sdk.contract_catalog import contract_catalog,contract_catalog_digest
    mirror=Path(__file__).resolve().parents[2]/'packages/interfaces/transport/client/python/src/ordessa_system_access_client/sdk-contract-catalog.json'
    expected={'schema':contract_catalog(),'schemaDigest':contract_catalog_digest()}
    if options.write:mirror.write_text(json.dumps(expected,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    if not mirror.is_file() or json.loads(mirror.read_text())!=expected:
        raise SystemExit('Current Agent SDK data schema mirror missing or differs; use --write after review')
    print('Current Agent SDK data schemas verified; old RPC client compatibility is not qualified')
    return 0


if __name__=='__main__':raise SystemExit(main())
