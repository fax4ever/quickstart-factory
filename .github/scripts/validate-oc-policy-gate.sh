#!/bin/bash
# Validates that OC-policy gate hook symlinks
# exist, are relative, and are not broken.
set -euo pipefail

POLICY_GATE_CLIENTS=(.claude)
POLICY_GATE_FILES=(openshift-policy.sh openshift-policy.yaml openshift-policy.example.yaml)
errors=0

for client in "${POLICY_GATE_CLIENTS[@]}"; do
  for hook in "${POLICY_GATE_FILES[@]}"; do
    link="$client/hooks/$hook"
    if [ ! -L "$link" ]; then
      echo "::error::missing hook symlink: $link"
      errors=$((errors + 1))
      continue
    fi
    target=$(readlink "$link")
    if [[ "$target" == /* ]]; then
      echo "::error::absolute hook symlink: $link -> $target (must be relative)"
      errors=$((errors + 1))
    fi
    if [ ! -e "$link" ]; then
      echo "::error::broken hook symlink: $link -> $target"
      errors=$((errors + 1))
    fi
  done

done

if [ "$errors" -gt 0 ]; then
  echo "::error::$errors OC-policy gate symlink error(s). Run 'bash core/scripts/sync-clients.sh' and commit."
  exit 1
fi
echo "✅ OC-policy gate symlinks verified."
