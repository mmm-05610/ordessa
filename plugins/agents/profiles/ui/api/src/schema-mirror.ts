import { AGENT_PROFILE_CATALOG_CONTRACT_VERSION } from './contract'

export interface AgentProfileCatalogSchemaMirror {
 readonly contractVersion: typeof AGENT_PROFILE_CATALOG_CONTRACT_VERSION
 readonly schemaDigest: string
 readonly schema: Readonly<Record<string, unknown>>
}
/** Generated current Profile data format; capability invocation uses operations.call. */
export const profileSchemaMirror: AgentProfileCatalogSchemaMirror = {
  "contractVersion": "profile-json/1",
  "schema": {
    "profileRef": {
      "additionalProperties": false,
      "properties": {
        "contentDigest": {
          "pattern": "^sha256:[0-9a-f]{64}$",
          "type": "string"
        },
        "environmentNamespace": {
          "pattern": "^[a-z][a-z0-9._-]{0,63}$",
          "type": "string"
        },
        "manifestRevision": {
          "minimum": 1,
          "type": "integer"
        },
        "profileId": {
          "pattern": "^[a-z][a-z0-9._-]{0,63}$",
          "type": "string"
        }
      },
      "required": [
        "environmentNamespace",
        "profileId",
        "manifestRevision",
        "contentDigest"
      ]
    },
    "results": {
      "catalogEntry": {
        "required": [
          "profileId",
          "catalogRevision",
          "displayName",
          "archivedAt",
          "currentManifestRef"
        ]
      },
      "list": {
        "required": [
          "entries"
        ]
      },
      "manifest": {
        "required": [
          "ref",
          "content"
        ]
      },
      "preview": {
        "required": [
          "profileRef",
          "status",
          "referenceCoverage",
          "ready",
          "error"
        ]
      }
    },
    "schemaVersion": "profile-json/1"
  },
  "schemaDigest": "sha256:a49dbe71ae8476c77f2fb29ab9c5e1f3040f1eb3c1c57e653035ef08c55a47eb"
}
