#!/usr/bin/env bash
# sync-clients.sh — Sync core skills and hooks to AI client directories as symlinks.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILLS_DIR="$ROOT_DIR/core/skills"
POLICY_GATE_DIR="$ROOT_DIR/core/oc-policy-gate"
CLIENTS=(.claude .codex .cursor .gemini)
POLICY_GATE_SUPPORTED_CLIENTS=(.claude)

POLICY_GATE_HOOK_FILES=(openshift-policy.sh openshift-policy.yaml openshift-policy.example.yaml)

# --- Skills ---
for client in "${CLIENTS[@]}"; do
  target="$ROOT_DIR/$client/skills"
  mkdir -p "$target"

  # Clean old symlinks
  for link in "$target"/*; do
    [ -L "$link" ] && rm -f "$link"
  done

  # Link each skill
  for skill_dir in "$SKILLS_DIR"/*/; do
    [ -f "$skill_dir/SKILL.md" ] || continue
    name="$(basename "$skill_dir")"
    # Relative link. Do not use GNU `ln -sr` — macOS ln has no -r.
    ln -s "../../core/skills/${name}" "$target/$name"
    echo "  ✓ $client/skills/$name"
  done
done

# --- Policy Gate hooks ---
for client in "${POLICY_GATE_SUPPORTED_CLIENTS[@]}"; do
  hooks_target="$ROOT_DIR/$client/hooks"
  mkdir -p "$hooks_target"

  # Clean old hook symlinks
  for link in "$hooks_target"/*; do
    [ -L "$link" ] && rm -f "$link"
  done

  # Link each hook file
  for file in "${POLICY_GATE_HOOK_FILES[@]}"; do
    [ -f "$POLICY_GATE_DIR/$file" ] || continue
    # Relative link. Do not use GNU `ln -sr` — macOS ln has no -r.
    ln -s "../../core/oc-policy-gate/${file}" "$hooks_target/$file"
    echo "  ✓ $client/hooks/$file"
  done

done

echo "✅ Sync complete."
