import { capturedLaunchText } from "./captured_launch.mjs"
import { captureLaunchCatalog } from "../../src/ordessa_server/composition/native_channels/launch_catalog.mjs"
import { selectedLaunchPorts } from "../../src/ordessa_server/composition/native_channels/selected_launch_ports.mjs"
import { bindLaunchPolicy } from "../../src/ordessa_server/composition/native_channels/launch_policy.mjs"
export const catalog=captureLaunchCatalog(capturedLaunchText(),selectedLaunchPorts)
export const {resolveManagedLaunch,resolveInstalledLaunch,resolveLegacyLaunch,installedLaunchReference,allowsPythonPath,launchDiscovery}=bindLaunchPolicy(catalog)
export const {harnessLaunchContext,registryIdentityVersionMatches,isKnownHarness,listCanonicalHarnesses,listHarnesses}=catalog
