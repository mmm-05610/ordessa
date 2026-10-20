#!/usr/bin/env python3
"""Generate the exact current Profile value-format mirror, no runtime /3 ABI."""
import json
from pathlib import Path
from ordessa_execution_agents.sdk.contract_catalog import profile_contract
ROOT=Path(__file__).resolve().parents[2]
OUTPUT=ROOT/'plugins/agents/profiles/ui/api/src/schema-mirror.ts'

def main():
    value=profile_contract()
    source="import { AGENT_PROFILE_CATALOG_CONTRACT_VERSION } from './contract'\n\n"
    source+="export interface AgentProfileCatalogSchemaMirror {\n readonly contractVersion: typeof AGENT_PROFILE_CATALOG_CONTRACT_VERSION\n readonly schemaDigest: string\n readonly schema: Readonly<Record<string, unknown>>\n}\n"
    source+="/** Generated current Profile data format; capability invocation uses operations.call. */\n"
    source+='export const profileSchemaMirror: AgentProfileCatalogSchemaMirror = '+json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    OUTPUT.write_text(source,encoding='utf-8')
if __name__=='__main__':main()
