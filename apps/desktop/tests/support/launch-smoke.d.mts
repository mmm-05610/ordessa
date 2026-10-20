export type SmokeDriverId = 'smoke' | 'probe-startup-ui'
export type SmokeEnvironment = Record<string, string | undefined>

export function buildSmokeEnvironment(
  home: string,
  extraEnv?: SmokeEnvironment,
  driverId?: SmokeDriverId,
): SmokeEnvironment & { ORDESSA_SMOKE_DRIVER_ID: SmokeDriverId }

export function launchSmoke(
  home: string,
  extraEnv?: SmokeEnvironment,
  options?: { driverId?: SmokeDriverId },
): Promise<unknown>
