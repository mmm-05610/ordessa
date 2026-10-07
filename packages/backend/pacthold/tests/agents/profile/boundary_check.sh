#!/usr/bin/env bash
# Dependency-direction gate (constitution II / plan §3): the Profile plugin
# family must not import host internals, sibling plugins or product packages.
set -u
SRC_DIR="$(cd "$(dirname "$0")/../src/ordessa_profile" && pwd)"
violations=0
while IFS= read -r file; do
  while IFS= read -r line; do
    echo "VIOLATION: $file: $line"
    violations=$((violations + 1))
  done < <(grep -nE "^\s*(import|from)\s+(ordessa_server|ordessa_server_compat|ordessa_harness|ordessa_workspace|ordessa_desktop|apps|products)\b" "$file")
done < <(find "$SRC_DIR" -name '*.py' -type f)
if [ "$violations" -ne 0 ]; then
  echo "boundary_check: FAIL ($violations violations)"
  exit 1
fi
echo "boundary_check: OK (0 violations; only 'pacthold' and stdlib imports allowed)"
exit 0
