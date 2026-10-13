import { nativeConfigurationReader as bind } from "../../../../../../../packages/execution/agents/src/ordessa_execution_agents/harness/configuration/acp/reader.mjs"
import { strategy } from "./strategy.mjs"
export function nativeConfigurationReader({agent,invalidParams}) { return bind({agent,strategy,invalidParams}) }
