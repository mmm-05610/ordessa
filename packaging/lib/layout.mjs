// The install layout, in exactly one place (C-09 A2). P-B parses this layout
// at runtime via `ORDESSA_BUNDLED_ROOT` (C-02 §6), so a typo here becomes a
// `BUNDLED_RUNTIME_MISSING` on every user machine -- the two sides are checked
// against each other by `verifyLayout`.

export const INSTALL_PREFIX = '/opt/ordessa'

export const layout = {
  prefix: INSTALL_PREFIX,
  python: `${INSTALL_PREFIX}/python`,
  pythonBin: `${INSTALL_PREFIX}/python/bin/python3.12`,
  sitePackages: `${INSTALL_PREFIX}/python/lib/python3.12/site-packages`,
  bin: `${INSTALL_PREFIX}/bin`,
  launcher: `${INSTALL_PREFIX}/bin/ordessa`,
  acp: `${INSTALL_PREFIX}/bin/acp`,
  harnesses: `${INSTALL_PREFIX}/harnesses`,
  app: `${INSTALL_PREFIX}/app`,
  licenses: `${INSTALL_PREFIX}/licenses`,
  notices: `${INSTALL_PREFIX}/licenses/THIRD-PARTY-NOTICES`,
  pubkey: `${INSTALL_PREFIX}/app/update-pubkey`,
  bundleManifest: `${INSTALL_PREFIX}/app/bundle-manifest.json`,
  buildInfo: `${INSTALL_PREFIX}/app/build-info.json`,
  desktop: '/usr/share/applications/ordessa.desktop',
  icons: '/usr/share/icons/hicolor',
  doc: '/usr/share/doc/ordessa',
}

// Files whose absence must abort the install rather than produce a half-usable
// app (C-02 §6: fail early and name what is missing, never "half available").
export const REQUIRED_AT_RUNTIME = [layout.launcher, layout.acp, layout.pythonBin]

export const ICON_SIZES = [16, 32, 48, 64, 128, 256]

export function iconDest(size) {
  return `${layout.icons}/${size}x${size}/apps/ordessa.png`
}
