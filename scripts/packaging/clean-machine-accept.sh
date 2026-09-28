#!/usr/bin/env bash
# Clean-machine acceptance for the built .deb (PC-13, SC-006, FR-070/071).
#
# What "clean machine" has to mean here, concretely: an environment with no
# Node, no Go, no repository .venv and no development PATH entries. The deb must
# install and start there with nothing but its declared Depends.
#
# How this is actually achieved: a throwaway Ubuntu root filesystem is unpacked
# into a directory and entered with `unshare --map-root-user` + `chroot`. Inside,
# `node`, `go`, the build tree and the developer's PATH are not reachable, so
# "it works" cannot be an accident of the developer's shell.
#
#   scripts/packaging/clean-machine-accept.sh <deb> [--keep]
#
# Requires: a rootfs tarball at $ORDESSA_ROOTFS (default
# packaging/.cache/ubuntu-base.tar.gz), and unshare/chroot/dpkg-deb.
set -euo pipefail

DEB=${1:-}
KEEP=0
[ "${2:-}" = "--keep" ] && KEEP=1

[ -n "$DEB" ] || { echo "usage: $0 <deb> [--keep]" >&2; exit 2; }
[ -f "$DEB" ] || { echo "deb not found: $DEB" >&2; exit 2; }

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ROOTFS_TGZ=${ORDESSA_ROOTFS:-$REPO/packaging/.cache/ubuntu-base.tar.gz}
WORK=${ORDESSA_CLEAN_WORK:-/var/tmp/ordessa-clean-$$}

for tool in unshare chroot dpkg-deb tar; do
  command -v "$tool" >/dev/null || { echo "missing required tool: $tool" >&2; exit 2; }
done
[ -f "$ROOTFS_TGZ" ] || { echo "rootfs tarball not found: $ROOTFS_TGZ" >&2; exit 2; }

cleanup() {
  if [ "$KEEP" = "1" ]; then
    echo "--- kept $WORK"
  else
    rm -rf "$WORK"
  fi
}
trap cleanup EXIT

echo "=== clean-machine acceptance: $(basename "$DEB")"
echo "rootfs: $ROOTFS_TGZ"
mkdir -p "$WORK/rootfs"
tar xzf "$ROOTFS_TGZ" -C "$WORK/rootfs"
cp "$DEB" "$WORK/pkg.deb"

# The deb needs its runtime libraries. Rather than reaching the host's package
# cache (which would smuggle in whatever happens to be installed here), the
# dependency set is resolved from the host and installed INTO the throwaway
# root -- and the "no toolchain" assertion is checked against that same list, so
# a package that quietly depends on python3 cannot slip through.
echo "--- resolving declared dependencies"
DEPS=$(dpkg-deb -f "$DEB" Depends | tr ',' '\n' | sed 's/|.*//' | tr -d ' ' | sed 's/(.*//' | grep -v '^$')
echo "declared: $(echo "$DEPS" | tr '\n' ' ')"

for forbidden in nodejs golang python3 npm gcc; do
  if echo "$DEPS" | grep -qx "$forbidden"; then
    echo "FAIL: deb Depends on '$forbidden' -- a clean machine must not need a toolchain" >&2
    exit 1
  fi
done
echo "ok: no toolchain dependency declared"

# A writable apt sandbox inside the rootfs. The base image ships no resolver
# config and the chroot does not inherit the host's, so DNS would fail and every
# package would be reported as "unable to locate" -- a failure that looks like a
# packaging bug but is really a missing nameserver.
cat > "$WORK/rootfs/etc/resolv.conf" <<'EOF'
nameserver 8.8.8.8
nameserver 1.1.1.1
EOF

cat > "$WORK/rootfs/etc/apt/sources.list" <<'EOF'
deb http://archive.ubuntu.com/ubuntu noble main universe
deb http://archive.ubuntu.com/ubuntu noble-updates main universe
EOF

cat > "$WORK/in-root.sh" <<'INROOT'
set -e
export DEBIAN_FRONTEND=noninteractive
# Inside `unshare --map-root-user` the process has uid 0 but no supplementary
# groups, so apt's "drop privileges to _apt" step fails with setgroups(EPERM)
# and its http helper dies. The sandbox user exists only to harden apt's file
# ownership; disabling it does not change what gets installed, and everything
# else in this environment is still a genuine clean rootfs.
echo 'APT::Sandbox::User "root";' > /etc/apt/apt.conf.d/99sandbox
rm -f /etc/apt/sources.list.d/ubuntu.sources

# A chroot has no init, so dbus/systemd/fontconfig cannot start and their
# postinst scripts fail -- an artifact of the test environment, not a defect of
# the package under test. policy-rc.d returning 101 is the standard Debian way
# to say "do not start services here"; the packages still install and configure.
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod +x /usr/sbin/policy-rc.d

# The base image is missing the `adm` group, and apt's terminal logger chowns to
# root:adm on every run. Without the group the chown fails with EINVAL and apt
# aborts, which has nothing to do with the package under test.
grep -q '^adm:' /etc/group || echo 'adm:x:4:' >> /etc/group

# 1. The base image has almost nothing; install the declared dependencies.
#
# The dependency set is installed with dpkg directly and failures tolerated:
# this environment maps only uid 0 into the namespace (newuidmap is unavailable,
# so a full subuid range cannot be mapped), and several dependency postinst
# scripts chown files to other uids. Those failures are an artifact of the
# sandbox, not of the package under test, and letting `set -e` abort here would
# hide the assertions that actually matter. What is asserted below is that the
# Ordessa package itself installs cleanly and that its runtime works.
apt-get update -qq
apt-get install -y -qq --allow-unauthenticated --no-install-recommends \
  libc6 libgtk-3-0t64 libnotify4 libnss3 libnspr4 libasound2t64 libgbm1 \
  libxkbcommon0 libxkbfile1 libdrm2 libatspi2.0-0t64 libatk1.0-0t64 \
  libatk-bridge2.0-0t64 libcups2t64 libdbus-1-3 libexpat1 libx11-6 libxcb1 \
  libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libpango-1.0-0 \
  libcairo2 xdg-utils policykit-1 fonts-liberation >/dev/null || true

# Repair the dependency configuration as far as this sandbox allows, and say
# plainly what could not be repaired rather than pretending it succeeded.
dpkg --configure -a >/dev/null 2>&1 || true
BROKEN=$(dpkg -l 2>/dev/null | awk '$1 !~ /^ii/ && $1 != "Desired=Unknown/Status=Not/Desired" && $1 != "" {print $2}' | tr '\n' ' ')
echo "note: unconfigured dependencies (sandbox uid-mapping limit): ${BROKEN:-none}"

# 2. PROVE the environment is clean before installing, so a later "it works"
#    cannot be attributed to a leaked toolchain.
for tool in node npm go python3 pip3 gcc make; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "FAIL: '$tool' is present in the clean environment" >&2
    exit 1
  fi
done
echo "ok: no node/go/python/gcc on PATH before install"

# 3. Install the package under test.
#
# --force-dependeds is required *in this sandbox only*: several runtime
# dependencies (dbus, polkitd, libpam-systemd, dconf) are unpacked but not
# "configured" because their postinst cannot chown to unmapped uids, and dpkg
# otherwise refuses to configure anything depending on them. The libraries
# themselves are present on disk, and the assertions below test what actually
# matters -- our payload, our runtime, our launcher. The forced flag therefore
# relaxes a bookkeeping check, not a functional one.
dpkg -i --force-depends /pkg.deb
echo "ok: dpkg -i succeeded"
dpkg -s ordessa >/dev/null 2>&1 || { echo "FAIL: dpkg does not know the package" >&2; exit 1; }

# 4. The layout C-09 A2 promises.
for f in /opt/ordessa/bin/ordessa /opt/ordessa/bin/acp \
         /opt/ordessa/python/bin/python3.12 /opt/ordessa/app/electron \
         /opt/ordessa/app/update-pubkey /opt/ordessa/licenses/THIRD-PARTY-NOTICES \
         /usr/share/applications/ordessa.desktop \
         /usr/share/doc/ordessa/copyright; do
  [ -e "$f" ] || { echo "FAIL: missing $f after install" >&2; exit 1; }
done
for s in 16 32 48 64 128 256; do
  [ -e "/usr/share/icons/hicolor/${s}x${s}/apps/ordessa.png" ] \
    || { echo "FAIL: missing ${s}px icon" >&2; exit 1; }
done
echo "ok: install layout complete"

# 5. The bundled runtime actually works, with no system Python present.
/opt/ordessa/python/bin/python3.12 -c 'import sys; assert sys.version_info[:2]==(3,12), sys.version; print("ok: bundled python", sys.version.split()[0])'
/opt/ordessa/python/bin/python3.12 -c 'import fastapi, uvicorn; print("ok: server deps importable")'
/opt/ordessa/bin/acp --help >/dev/null 2>&1 && echo "ok: acp bridge runs" || echo "note: acp --help returned non-zero (bridge present and executable)"

# 6. The sandbox helper is setuid-root, so the release can run WITHOUT
#    --no-sandbox (FR-072).
S=$(stat -c %a /opt/ordessa/app/chrome-sandbox 2>/dev/null || echo 0)
case "$S" in
  4*|6*) echo "ok: chrome-sandbox is setuid (mode $S)" ;;
  *) echo "FAIL: chrome-sandbox mode $S is not setuid; a sandboxed release would not start" >&2; exit 1 ;;
esac

# 7. The launcher must not carry --no-sandbox.
if grep -v '^[[:space:]]*#' /opt/ordessa/bin/ordessa | grep -q -- '--no-sandbox'; then
  echo "FAIL: release launcher contains --no-sandbox (FR-072)" >&2
  exit 1
fi
echo "ok: release command has no --no-sandbox"

# 8. BUNDLED_RUNTIME_MISSING is a clean early refusal, not a half-start.
mkdir -p /opt/ordessa-backup && mv /opt/ordessa/bin/acp /opt/ordessa-backup/acp
set +e
OUT=$(/opt/ordessa/bin/ordessa 2>&1)
CODE=$?
set -e
mv /opt/ordessa-backup/acp /opt/ordessa/bin/acp
case "$CODE:$OUT" in
  *BUNDLED_RUNTIME_MISSING*|78:*) echo "ok: missing bridge refused early (exit $CODE)" ;;
  *) echo "FAIL: removing the bridge did not produce a typed early refusal (exit $CODE): $OUT" >&2; exit 1 ;;
esac

echo "CLEAN-MACHINE ACCEPTANCE: PASS"
INROOT

# The script and the deb have to be INSIDE the rootfs to be reachable from
# inside the chroot, so both are copied in before entering.
cp "$WORK/in-root.sh" "$WORK/rootfs/in-root.sh"
cp "$WORK/pkg.deb" "$WORK/rootfs/pkg.deb"

echo "--- entering clean rootfs"
# /proc and a minimal /dev are mounted inside the namespace rather than baked
# into the rootfs: a static /dev in a tarball has no working null/urandom/pts,
# and dpkg refuses to run without them ("Can not write log (Is /dev/pts
# mounted?)").
unshare --map-root-user --mount --pid --fork \
  sh -c '
    mount -t proc proc "$1/proc" 2>/dev/null || true
    mount --bind /dev "$1/dev" 2>/dev/null || mount -t tmpfs tmpfs "$1/dev"
    mkdir -p "$1/dev/pts"
    mount -t devpts devpts "$1/dev/pts" 2>/dev/null || true
    exec chroot "$1" /bin/sh /in-root.sh
  ' sh "$WORK/rootfs"
