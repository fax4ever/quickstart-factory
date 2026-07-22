#!/usr/bin/env bash
# sync-clients.sh — Sync core skills and hooks to AI client directories as symlinks.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILLS_DIR="$ROOT_DIR/core/skills"
POLICY_GATE_DIR="$ROOT_DIR/core/oc-policy-gate"
CLIENTS=(.claude .codex .cursor .gemini)
POLICY_GATE_SUPPORTED_CLIENTS=(.claude)

POLICY_GATE_HOOK_FILES=(openshift-policy.sh openshift-policy.yaml openshift-policy.example.yaml)

# Map client name → settings source file from oc-policy-gate.
declare -A POLICY_GATE_SETTINGS
POLICY_GATE_SETTINGS[.claude]="settings.claude_example.json"

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
    ln -sr "$skill_dir" "$target/$name"
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
    ln -sr "$POLICY_GATE_DIR/$file" "$hooks_target/$file"
    echo "  ✓ $client/hooks/$file"
  done

  # Link settings file
  settings_src="${POLICY_GATE_SETTINGS[$client]:-}"
  if [[ -n "$settings_src" && -f "$POLICY_GATE_DIR/$settings_src" ]]; then
    settings_target="$ROOT_DIR/$client/settings.json"
    if [ -e "$settings_target" ]; then
      echo "  ⚠ $client/settings.json already exists — merge settings manually from $POLICY_GATE_DIR/$settings_src"
    else
      ln -sr "$POLICY_GATE_DIR/$settings_src" "$settings_target"
      echo "  ✓ $client/settings.json"
    fi
  fi
done

echo "✅ Sync complete."
