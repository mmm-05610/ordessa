import { findExecutable } from "./executable_lookup.mjs"
export function resolveAcpLaunch(profile, { find = findExecutable } = {}) {
  if (!profile.adapterCommand) return { command: profile.command, args: [...profile.args], source: "harness" }
  const installed = find(profile.adapterCommand)
  if (installed) return { command: installed, args: [], source: "path" }
  return { command: profile.command, args: [...profile.args], source: "npx" }
}
