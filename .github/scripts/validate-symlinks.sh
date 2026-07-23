#!/bin/bash
# Validates that each AI-client skills directory has the expected symlinks
# pointing back to core/skills/, and that none are absolute or broken.
set -euo pipefail

SKILL_CLIENTS=(.claude .codex .cursor .gemini)
errors=0

expected=$(find core/skills -name SKILL.md | wc -l | tr -d ' ')

for client in "${SKILL_CLIENTS[@]}"; do
  linked=$(find "$client/skills" -maxdepth 1 -type l 2>/dev/null | wc -l | tr -d ' ')
  echo "[$client/skills] expected=$expected linked=$linked"
  if [ "$expected" != "$linked" ]; then
    echo "::error::$client/skills has $linked symlinks, expected $expected"
    errors=$((errors + 1))
  fi
  for link in "$client/skills/"*; do
    [ -L "$link" ] || continue
    target=$(readlink "$link")
    if [[ "$target" == /* ]]; then
      echo "::error::absolute symlink: $link -> $target (must be relative)"
      errors=$((errors + 1))
    fi
    if [ ! -e "$link" ]; then
      echo "::error::broken symlink: $link -> $target"
      errors=$((errors + 1))
    fi
  done
done

if [ "$errors" -gt 0 ]; then
  echo "::error::$errors skill symlink error(s). Run 'bash core/scripts/sync-clients.sh' and commit."
  exit 1
fi
echo "✅ Skill symlinks verified."
