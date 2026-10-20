import { readFileSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import * as bridge0 from "../../../plugins/harness/codex/src/ordessa_harness_codex/acp/profile/bridge.mjs"
import * as reader0 from "../../../plugins/harness/codex/src/ordessa_harness_codex/acp/profile/configuration-query.mjs"
import * as route0 from "../../../plugins/harness/codex/src/ordessa_harness_codex/acp/profile/routing.mjs"
import * as enhance0 from "../../../plugins/harness/codex/tooling/profile_enhancement.mjs"
import * as bridge1 from "../../../plugins/harness/claude-code/src/ordessa_harness_claude_code/acp/profile/bridge.mjs"
import * as reader1 from "../../../plugins/harness/claude-code/src/ordessa_harness_claude_code/acp/profile/configuration-query.mjs"
import * as route1 from "../../../plugins/harness/claude-code/src/ordessa_harness_claude_code/acp/profile/routing.mjs"
import * as enhance1 from "../../../plugins/harness/claude-code/tooling/profile_enhancement.mjs"
const ports=Object.freeze({codex:Object.freeze({bridge:bridge0,reader:reader0,route:route0,enhance:enhance0}),"claude-code":Object.freeze({bridge:bridge1,reader:reader1,route:route1,enhance:enhance1})})
function port(brand) {if(!Object.hasOwn(ports,brand)) throw new Error("Native Profile upstream source digest mismatch");return ports[brand]}
export function nativeProfileBridge(agent,brand,invalidParams) {return port(brand).bridge.nativeProfileBridge(agent,invalidParams)}
export function nativeConfigurationReader({agent,brand,invalidParams}) {return port(brand).reader.nativeConfigurationReader({agent,invalidParams})}
export function enhanceSource(source,brand) {return port(brand).enhance.enhanceSource(source)}
export function enhancementTemplateResources(brand) {return port(brand).enhance.enhancementTemplateResources()}
export function captureCodexThreadRoute(...args) {return route0.captureCodexThreadRoute(...args)}
export function safeNativeRoute(input) {return route0.safeNativeRoute(input) ?? route1.safeNativeRoute(input)}
export function entrySource(brand) {return port(brand).enhance.enhancementTemplateResources()["ordessa-profile.mjs"]}
export function entryText(brand) {
 const source=entrySource(brand)
 return readFileSync(source,'utf8').replace(/from (["'])(\.[^"']+)\1/u, (whole,quote,specifier) => 'from '+quote+pathToFileURL(path.resolve(path.dirname(source),specifier)).href+quote)
}
