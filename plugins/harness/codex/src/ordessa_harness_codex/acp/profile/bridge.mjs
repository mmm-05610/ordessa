import { nativeProfileBridge as bind } from "../../../../../../../packages/execution/agents/src/ordessa_agents/harness/configuration/acp/bridge.mjs"
import { strategy } from "./strategy.mjs"
export function nativeProfileBridge(agent, invalidParams) { return bind(agent, strategy, invalidParams) }
