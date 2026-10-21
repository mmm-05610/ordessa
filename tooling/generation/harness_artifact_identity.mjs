import { spawnSync } from 'node:child_process'
import path from 'node:path'
export function artifactIdentityResult(directory,{sourceRoots,environment=process.env,python='python3'}) {
  if (!Array.isArray(sourceRoots) || sourceRoots.some(root => typeof root !== 'string' || !path.isAbsolute(root)))
    throw new TypeError('Explicit digest source roots required')
  const program = ["import json, sys", "from ordessa_agents.harness.providers.resolution.artifacts.tree_identity import runtime_artifact_tree_summary as summary", "print(json.dumps(summary(sys.argv[1])))"].join('; ')
  return spawnSync(python,['-c',program,directory],{env:{...environment,PYTHONPATH:[...sourceRoots,...(environment.PYTHONPATH ? [environment.PYTHONPATH] : [])].join(path.delimiter)},encoding:'utf8'})
}
